import time
import struct
from datetime import datetime
from stuffing import bit_stuffing, bit_destuffing, ajouter_flags, extraire_entre_flags
from canal import Canal


TAILLE_MAX_DATA = 100  # Taille maximale des donnees par trame (octets)
FLAG = 0b01111110      
TIMEOUT = 0.25         # Timeout en secondes (250ms)

# Types de trames
TYPE_DATA = 0
TYPE_ACK = 1

def calculer_crc16(data):
    """
    Calcule le CRC-16 CCITT (polynome 0x1021)
    Methode compatible avec verification 'reste = 0'
    """
    crc = 0xFFFF  # Initialisation
    
    for byte in data:
        # XOR l'octet dans les 8 bits de poids fort
        crc = crc ^ (byte << 8)
        
        # Traiter chaque bit
        for _ in range(8):
            if crc & 0x8000:  # Si bit de poids fort = 1
                crc = (crc << 1) ^ 0x1021  # Shift et XOR avec polynome
            else:
                crc = crc << 1  # Juste shift
            
            # Garder seulement 16 bits
            crc = crc & 0xFFFF
    
    return crc

def get_timestamp():
    # Fonction pour les timestamp dans les logs
    maintenant = datetime.now()
    timestamp = maintenant.strftime("%H:%M:%S.%f")[:-3]
    return timestamp

class Trame:
    # Represente une trame de donnees ou un ACK
    # Format: [num_seq(1B)] [type(1B)] [longueur(2B)] [donnees(0-100B)] [crc(2B)]

    def __init__(self, num_seq, data, type_trame=TYPE_DATA):
        self.num_seq = num_seq
        self.data = data
        self.type_trame = type_trame
    
    
    def serialiser(self):
        # Convertit la trame en bytes (prete a etre transmise)

        # Determiner le type
        type_byte = 0 if self.type_trame == TYPE_DATA else 1
        
        # Longueur des donnees
        data_len = len(self.data) if self.data else 0
        
        # Construire l'en-tete: num_seq (1B) + type (1B) + longueur (2B)
        # '!' = network byte order (big-endian)
        # 'B' = unsigned char (1 octet)
        # 'H' = unsigned short (2 octets)
        header = struct.pack('!BBH', self.num_seq, type_byte, data_len)
        
        # Corps = en-tete + donnees
        if self.data:
            corps = header + self.data
        else:
            corps = header
        
        # Calculer le CRC sur le corps (en-tete + donnees)
        crc = calculer_crc16(corps)
        
        # Trame complete = corps + crc
        # 'H' = unsigned short (2 octets) pour le CRC
        trame_bytes = corps + struct.pack('!H', crc)
        
        return trame_bytes
    
    
    @staticmethod
    def deserialiser(trame_bytes):
        # Reconstruit une trame depuis bytes
        # Args:trame_bytes: bytes recus
        # Returns:(Trame, crc_valide) ou (None, False) si erreur

        # Verifier la taille minimale: header(4) + crc(2) = 6 octets
        if len(trame_bytes) < 6:
            return None, False
        
        # Extraire l'en-tete (4 premiers octets)
        num_seq, type_byte, data_len = struct.unpack('!BBH', trame_bytes[:4])
        
        # Verifier que la taille est coherente
        taille_attendue = 4 + data_len + 2  # header + data + crc
        if len(trame_bytes) < taille_attendue:
            return None, False
        
        # Extraire les donnees (si presentes)
        if data_len > 0:
            data = trame_bytes[4:4+data_len]
        else:
            data = b''
        
        # Extraire le CRC (2 derniers octets de la partie attendue)
        crc_recu = struct.unpack('!H', trame_bytes[4+data_len:4+data_len+2])[0]
        
        # Calculer le CRC sur la trame complete (corps + crc recu)
        # Si aucune erreur, le reste de la division doit etre 0
        trame_complete = trame_bytes[:4+data_len+2]
        reste = calculer_crc16(trame_complete)
        
        # Verifier si le reste est 0
        crc_valide = (reste == 0)
        
        # Reconstruire la trame
        type_trame = TYPE_DATA if type_byte == 0 else TYPE_ACK
        trame = Trame(num_seq, data, type_trame)
        
        return trame, crc_valide
    
class Emetteur:
    # Emetteur de trames avec Go-Back-N
    # Gere l'envoi, les timeouts et les retransmissions
    
    def __init__(self, canal, timeout=TIMEOUT, taille_fenetre=5):
        self.canal = canal
        self.timeout = timeout
        self.taille_fenetre = taille_fenetre
        
        # Numero de sequence courant
        self.num_seq = 0
        
        # Statistiques
        self.trames_envoyees = 0
        self.trames_retransmises = 0
        self.acks_recus = 0

    def _segmenter(self, message):
        """
        Segmente le message en chunks de TAILLE_MAX_DATA octets
        
        Args:
            message: bytes du message complet
        
        Returns:
            liste de bytes (chaque element = 1 trame de donnees)
        """
        chunks = []
        
        # Parcourir le message par blocs de TAILLE_MAX_DATA
        for i in range(0, len(message), TAILLE_MAX_DATA):
            # Extraire un chunk
            chunk = message[i:i+TAILLE_MAX_DATA]
            chunks.append(chunk)
        
        return chunks
    
    def _envoyer_trame(self, num_seq, data, retransmission=False):
        """
        Envoie UNE trame de donnees via le canal
        
        Args:
            num_seq: numero de sequence
            data: bytes de donnees
            retransmission: True si c'est une retransmission
        
        Returns:
            bytes de la trame transmise (ou None si perdue)
        """
        # Creer la trame
        trame = Trame(num_seq, data, TYPE_DATA)
        trame_bytes = trame.serialiser()
        
        # Afficher l'evenement
        if retransmission:
            print(f"[{get_timestamp()}] RETRANSMISSION trame #{num_seq} ({len(data)} octets)")
            self.trames_retransmises += 1
        else:
            print(f"[{get_timestamp()}] Envoi trame #{num_seq} ({len(data)} octets)")
            self.trames_envoyees += 1
        
        # Stocker dans le buffer pour retransmission eventuelle
        self.buffer_trames[num_seq] = data
        
        # Enregistrer le temps d'envoi
        self.temps_envoi[num_seq] = time.time()
        
        # Transmettre via le canal
        trame_transmise = self.canal.transmettre(trame_bytes)
        
        return trame_transmise
    
    def envoyer_message_gobackn(self, fichier_path):
        """
        Envoie un fichier complet avec Go-Back-N et fenetre glissante
        
        Args:
            fichier_path: chemin du fichier a transmettre
        
        Returns:
            dictionnaire avec statistiques
        """
        print(f"\n{'='*60}")
        print(f"TRANSMISSION AVEC GO-BACK-N")
        print(f"Fichier: {fichier_path}")
        print(f"Fenetre: {self.taille_fenetre} trames")
        print(f"Timeout: {self.timeout*1000}ms")
        print(f"{'='*60}\n")
        
        # Lire le fichier
        with open(fichier_path, 'rb') as f:
            message = f.read()
        
        print(f"Taille du fichier: {len(message)} octets")
        
        # Segmenter en trames
        trames_data = self._segmenter(message)
        nb_trames_total = len(trames_data)
        print(f"Segmente en {nb_trames_total} trames\n")
        
        # Reinitialiser les variables
        self.base = 0
        self.next_seq = 0
        self.buffer_trames = {}
        self.temps_envoi = {}
        
        temps_debut = time.time()
        
        # ========================================================================
        # BOUCLE PRINCIPALE GO-BACK-N
        # ========================================================================
        
        while self.base < nb_trames_total:
            
            # 1. ENVOYER les trames dans la fenetre
            while self.next_seq < self.base + self.taille_fenetre and self.next_seq < nb_trames_total:
                data = trames_data[self.next_seq]
                self._envoyer_trame(self.next_seq, data, retransmission=False)
                self.next_seq += 1
                
                # Petit delai pour ne pas saturer
                time.sleep(0.01)
            
            # 2. ATTENDRE un peu pour recevoir des ACKs
            time.sleep(0.05)
            
            # 3. VERIFIER les timeouts
            trame_timeout = self._verifier_timeouts()
            
            if trame_timeout is not None:
                # TIMEOUT detecte ! Go-Back-N : retransmettre depuis base
                print(f"\n{'='*60}")
                print(f"GO-BACK-N : Retransmission depuis trame #{self.base}")
                print(f"{'='*60}\n")
                
                # Retransmettre toutes les trames de [base à next_seq-1]
                for num_seq in range(self.base, self.next_seq):
                    if num_seq in self.buffer_trames:
                        data = self.buffer_trames[num_seq]
                        self._envoyer_trame(num_seq, data, retransmission=True)
                        time.sleep(0.01)
            
            # Petit delai avant la prochaine iteration
            time.sleep(0.05)
        
        # ========================================================================
        # FIN DE LA TRANSMISSION
        # ========================================================================
        
        duree = time.time() - temps_debut
        
        print(f"\n{'='*60}")
        print("Transmission terminee.")
        print(f"Frames envoyees : {self.trames_envoyees}")
        print(f"Frames retransmises : {self.trames_retransmises}")
        print(f"ACK recus : {self.acks_recus}")
        print(f"Duree totale : {duree:.2f} s")
        print(f"{'='*60}\n")
        
        return {
            'envoyees': self.trames_envoyees,
            'retransmises': self.trames_retransmises,
            'acks': self.acks_recus,
            'duree': duree
        }
    
    def _verifier_timeouts(self):
        """
        Verifie si des trames ont timeout
        Retourne le numero de la premiere trame en timeout, ou None
        """
        temps_actuel = time.time()
        
        # Verifier toutes les trames dans la fenetre
        for num_seq in range(self.base, self.next_seq):
            if num_seq in self.temps_envoi:
                temps_ecoule = temps_actuel - self.temps_envoi[num_seq]
                
                if temps_ecoule > self.timeout:
                    print(f"[{get_timestamp()}] ⏱️  TIMEOUT trame #{num_seq}")
                    return num_seq
        
        return None
    
class Recepteur:
    """
    Recepteur de trames
    Verifie le CRC, envoie les ACKs, recompose le message
    """
    
    def __init__(self, canal):
        """
        Constructeur du recepteur
        
        Args:
            canal: objet Canal pour transmettre les ACKs
        """
        self.canal = canal
        
        # Liste pour stocker les trames recues: (num_seq, data)
        self.trames_recues = []
        
        # Dernier numero de sequence recu correctement
        self.dernier_num_seq = -1
        
        # Statistiques
        self.trames_acceptees = 0
        self.trames_rejetees = 0
        self.acks_envoyes = 0
    
    
    def recevoir_trame(self, trame_bytes):
        """
        Recoit et traite UNE trame
        
        Args:
            trame_bytes: bytes de la trame recue
        
        Returns:
            True si trame acceptee, False sinon
        """
        # Si la trame est None (perdue dans le canal), ignorer
        if trame_bytes is None:
            print(f"[{get_timestamp()}] Trame perdue (None)")
            return False
        
        # Deserialiser la trame
        trame, crc_valide = Trame.deserialiser(trame_bytes)
        
        # Si la trame est invalide ou CRC incorrect
        if trame is None or not crc_valide:
            print(f"[{get_timestamp()}] Trame corrompue - CRC ERREUR")
            self.trames_rejetees = self.trames_rejetees + 1
            return False
        
        # Afficher reception
        print(f"[{get_timestamp()}] Reception trame #{trame.num_seq} - CRC OK")
        
        # Go-Back-N: accepter seulement si num_seq = dernier + 1
        if trame.num_seq == self.dernier_num_seq + 1:
            # Trame attendue, accepter
            self.trames_recues.append((trame.num_seq, trame.data))
            self.dernier_num_seq = trame.num_seq
            self.trames_acceptees = self.trames_acceptees + 1
            
            # Envoyer ACK
            self._envoyer_ack(trame.num_seq)
            
            return True
        else:
            # Trame hors ordre (duplicata ou saut), rejeter
            print(f"[{get_timestamp()}] Trame #{trame.num_seq} hors ordre (attendu #{self.dernier_num_seq + 1})")
            self.trames_rejetees = self.trames_rejetees + 1
            
            # Renvoyer ACK du dernier accepte (Go-Back-N)
            if self.dernier_num_seq >= 0:
                self._envoyer_ack(self.dernier_num_seq)
            
            return False
    
    
    def _envoyer_ack(self, num_seq):
        """
        Envoie un ACK pour une trame
        
        Args:
            num_seq: numero de sequence a accuser
        """
        # Creer un ACK (trame sans donnees)
        ack = Trame(num_seq, b'', TYPE_ACK)
        ack_bytes = ack.serialiser()
        
        print(f"[{get_timestamp()}] Envoi ACK #{num_seq}")
        
        # Transmettre l'ACK via le canal
        self.canal.transmettre(ack_bytes)
        self.acks_envoyes = self.acks_envoyes + 1
    
    
    def recomposer_message(self):
        """
        Recompose le message complet a partir des trames recues
        
        Returns:
            bytes du message original
        """
        # Trier par numero de sequence (normalement deja dans l'ordre)
        self.trames_recues.sort(key=lambda x: x[0])
        
        # Concatener toutes les donnees
        message = b''
        for num_seq, data in self.trames_recues:
            message = message + data
        
        return message
    
    
    def verifier_message(self, fichier_original):
        """
        Compare le message recu avec le fichier original
        
        Args:
            fichier_original: chemin du fichier original
        
        Returns:
            True si identique, False sinon
        """
        # Lire le fichier original
        with open(fichier_original, 'rb') as f:
            message_original = f.read()
        
        # Recomposer le message recu
        message_recu = self.recomposer_message()
        
        # Comparer
        identique = (message_original == message_recu)
        
        print(f"\n{'='*60}")
        print("VERIFICATION DU MESSAGE")
        print(f"{'='*60}")
        print(f"Taille originale : {len(message_original)} octets")
        print(f"Taille recue     : {len(message_recu)} octets")
        print(f"Messages identiques : {identique}")
        print(f"{'='*60}\n")
        
        return identique

def simulation_gobackn(fichier_path, probErreur=0.05, probPerte=0.10, delaiMax=0.02, 
                       timeout=TIMEOUT, taille_fenetre=5, max_tentatives=5):
    """
    Simulation GO-BACK-N CORRECTE avec separation emetteur/recepteur
    """
    print("\n" + "="*70)
    print("SIMULATION GO-BACK-N")
    print("="*70)
    print(f"Fichier: {fichier_path}")
    print(f"Parametres: erreur={probErreur}, perte={probPerte}, delai={delaiMax*1000}ms")
    print(f"Timeout: {timeout*1000}ms, Fenetre: {taille_fenetre}")
    print("="*70 + "\n")
    
    canal = Canal(probErreur=probErreur, probPerte=probPerte, delaiMax=delaiMax)
    emetteur = Emetteur(canal, timeout=timeout, taille_fenetre=taille_fenetre)
    recepteur = Recepteur(canal)
    
    with open(fichier_path, 'rb') as f:
        message = f.read()
    
    print(f"Taille: {len(message)} octets")
    trames_data = emetteur._segmenter(message)
    nb_trames_total = len(trames_data)
    print(f"Segmente en {nb_trames_total} trames\n")
    
    # Variables EMETTEUR (ce qu'il sait)
    base_emetteur = 0  # Ce que l'emetteur croit avoir envoye avec succes
    tentatives = [0] * nb_trames_total
    temps_debut = time.time()
    
    print("Debut transmission...\n")
    
    # ========================================================================
    # BOUCLE PRINCIPALE
    # ========================================================================
    
    while base_emetteur < nb_trames_total:
        
        fin_fenetre = min(base_emetteur + taille_fenetre, nb_trames_total)
        
        print(f"[{get_timestamp()}] 📊 Fenetre emetteur: [{base_emetteur}, {fin_fenetre-1}], Recepteur attend: #{recepteur.dernier_num_seq + 1}")
        
        # ----------------------------------------------------------------
        # ENVOYER LA FENETRE ET ATTENDRE LES ACKs
        # ----------------------------------------------------------------
        
        acks_recus_cette_fenetre = set()
        
        for num_seq in range(base_emetteur, fin_fenetre):
            
            # Verifier tentatives
            if tentatives[num_seq] >= max_tentatives:
                print(f"[{get_timestamp()}] ❌ ABANDON trame #{num_seq}")
                base_emetteur += 1
                continue
            
            data = trames_data[num_seq]
            trame = Trame(num_seq, data, TYPE_DATA)
            trame_bytes = trame.serialiser()
            
            # Afficher
            if tentatives[num_seq] > 0:
                print(f"[{get_timestamp()}] 🔄 RETRANS trame #{num_seq} (tentative {tentatives[num_seq] + 1})")
                emetteur.trames_retransmises += 1
            else:
                print(f"[{get_timestamp()}] 📤 Envoi trame #{num_seq}")
                emetteur.trames_envoyees += 1
            
            tentatives[num_seq] += 1
            
            # ============================================================
            # PHASE 1: TRANSMETTRE LA TRAME
            # ============================================================
            trame_transmise = canal.transmettre(trame_bytes)
            time.sleep(delaiMax)
            
            if trame_transmise is None:
                print(f"[{get_timestamp()}]   ❌ Trame PERDUE dans canal")
                # Ne pas continuer la fenetre, attendre timeout
                break
            
            # ============================================================
            # PHASE 2: RECEPTEUR TRAITE LA TRAME
            # ============================================================
            trame_recue, crc_valide = Trame.deserialiser(trame_transmise)
            
            if not crc_valide:
                print(f"[{get_timestamp()}]   ❌ Trame CORROMPUE (CRC)")
                recepteur.trames_rejetees += 1
                # Recepteur ne fait rien, pas d'ACK
                break
            
            # Verifier ordre (Go-Back-N strict)
            if trame_recue.num_seq == recepteur.dernier_num_seq + 1:
                # Trame acceptee
                print(f"[{get_timestamp()}]   ✅ Recepteur accepte trame #{num_seq}")
                recepteur.trames_recues.append((num_seq, data))
                recepteur.dernier_num_seq = num_seq
                recepteur.trames_acceptees += 1
                
                # Envoyer ACK
                ack = Trame(num_seq, b'', TYPE_ACK)
                ack_bytes = ack.serialiser()
                print(f"[{get_timestamp()}]   📨 Recepteur envoie ACK #{num_seq}")
                
                ack_transmis = canal.transmettre(ack_bytes)
                recepteur.acks_envoyes += 1
                time.sleep(delaiMax)
                
                # ============================================================
                # PHASE 3: EMETTEUR RECOIT (ou pas) L'ACK
                # ============================================================
                if ack_transmis is not None:
                    # ACK arrive a l'emetteur
                    print(f"[{get_timestamp()}]   ✅ Emetteur recoit ACK #{num_seq}")
                    emetteur.acks_recus += 1
                    acks_recus_cette_fenetre.add(num_seq)
                else:
                    # ACK perdu
                    print(f"[{get_timestamp()}]   ❌ ACK #{num_seq} PERDU dans canal")
                    # L'emetteur ne sait pas que la trame est arrivee
                    # Il va timeout plus tard
                    break
            
            else:
                # Trame hors ordre (duplicata ou saut)
                print(f"[{get_timestamp()}]   ⚠️  Trame #{num_seq} hors ordre (recepteur attend #{recepteur.dernier_num_seq + 1})")
                recepteur.trames_rejetees += 1
                
                # Go-Back-N: Recepteur renvoie ACK du dernier recu
                if recepteur.dernier_num_seq >= 0:
                    ack_dernier = Trame(recepteur.dernier_num_seq, b'', TYPE_ACK)
                    ack_dernier_bytes = ack_dernier.serialiser()
                    print(f"[{get_timestamp()}]   📨 Recepteur renvoie ACK #{recepteur.dernier_num_seq} (duplicata)")
                    canal.transmettre(ack_dernier_bytes)
                
                # Arreter l'envoi de cette fenetre
                break
        
        # ----------------------------------------------------------------
        # AVANCER BASE EMETTEUR
        # ----------------------------------------------------------------
        
        ancien_base = base_emetteur
        
        # Avancer base pour tous les ACKs recus consecutifs
        while base_emetteur in acks_recus_cette_fenetre:
            base_emetteur += 1
        
        if base_emetteur > ancien_base:
            print(f"[{get_timestamp()}] 📊 Base emetteur avance: {ancien_base} → {base_emetteur}\n")
        else:
            # Aucun ACK recu, timeout
            print(f"[{get_timestamp()}] ⏱️  TIMEOUT: Aucun ACK recu, GO-BACK-N depuis base={base_emetteur}\n")
            time.sleep(timeout * 0.5)  # Petite pause avant retransmission
        
        time.sleep(0.01)
    
    # ========================================================================
    # FIN
    # ========================================================================
    
    duree = time.time() - temps_debut
    
    print("\n" + "="*70)
    print("RESULTATS - EMETTEUR")
    print("="*70)
    print(f"Frames envoyees     : {emetteur.trames_envoyees}")
    print(f"Frames retransmises : {emetteur.trames_retransmises}")
    print(f"ACK recus           : {emetteur.acks_recus}")
    print(f"Duree totale        : {duree:.2f} s")
    print("="*70)
    
    print("\n" + "="*70)
    print("RESULTATS - RECEPTEUR")
    print("="*70)
    print(f"Trames acceptees : {recepteur.trames_acceptees}")
    print(f"Trames rejetees  : {recepteur.trames_rejetees}")
    print(f"ACKs envoyes     : {recepteur.acks_envoyes}")
    print("="*70)
    
    message_recu = recepteur.recomposer_message()
    
    print("\n" + "="*70)
    print("VERIFICATION")
    print("="*70)
    print(f"Taille originale : {len(message)} octets")
    print(f"Taille recue     : {len(message_recu)} octets")
    print(f"Identiques       : {message == message_recu}")
    
    if message == message_recu:
        print("✅ SUCCES: Transmission complete!")
    else:
        print("❌ ECHEC: Message incomplet")
        print(f"Trames recues: {len(recepteur.trames_recues)}/{nb_trames_total}")
    
    print("="*70 + "\n")
    
    canal.afficher_statistiques()
    
    taux = (emetteur.trames_retransmises / emetteur.trames_envoyees * 100) if emetteur.trames_envoyees > 0 else 0
    
    return {
        'envoyees': emetteur.trames_envoyees,
        'retransmises': emetteur.trames_retransmises,
        'acks': emetteur.acks_recus,
        'duree': duree,
        'succes': message == message_recu,
        'taux_retransmission': taux
    }

if __name__ == "__main__":
    # print("\n" + "="*70)
    # print(" TESTS UNITAIRES - PROTOCOLE DE LIAISON")
    # print("="*70)
    
    # # ========================================================================
    # # TEST 1: Fonction calculer_crc16()
    # # ========================================================================
    # print("\n>>> TEST 1: Calcul du CRC-16")
    # print("-" * 70)
    
    # data1 = b"Hello"
    # crc1 = calculer_crc16(data1)
    # print(f"CRC de 'Hello': {crc1} (0x{crc1:04X})")
    
    # data2 = b"Helo"  # 1 lettre differente
    # crc2 = calculer_crc16(data2)
    # print(f"CRC de 'Helo':  {crc2} (0x{crc2:04X})")
    
    # if crc1 != crc2:
    #     print("✓ CRCs differents pour donnees differentes")
    # else:
    #     print("✗ ERREUR: CRCs identiques!")
    
    # # Test verification reste = 0
    # print("\nTest verification 'reste = 0':")
    # trame_test = data1 + struct.pack('!H', crc1)
    # reste = calculer_crc16(trame_test)
    # print(f"Reste pour (data + CRC): {reste}")
    # if reste == 0:
    #     print("✓ Reste = 0 (verification correcte)")
    # else:
    #     print("✗ ERREUR: Reste != 0")
    
    
    # # ========================================================================
    # # TEST 2: Classe Trame - Serialisation/Deserialisation
    # # ========================================================================
    # print("\n>>> TEST 2: Classe Trame")
    # print("-" * 70)
    
    # # Creer une trame DATA
    # trame1 = Trame(num_seq=5, data=b"Test123", type_trame=TYPE_DATA)
    # print(f"Trame creee: num_seq={trame1.num_seq}, data={trame1.data}, type={trame1.type_trame}")
    
    # # Serialiser
    # trame_bytes = trame1.serialiser()
    # print(f"Serialisee: {len(trame_bytes)} octets")
    # print(f"  Hex: {trame_bytes.hex()}")
    
    # # Deserialiser
    # trame2, crc_ok = Trame.deserialiser(trame_bytes)
    # if trame2 is not None:
    #     print(f"Deserialise: num_seq={trame2.num_seq}, data={trame2.data}, CRC valide={crc_ok}")
        
    #     if crc_ok and trame2.data == trame1.data:
    #         print("✓ Serialisation/Deserialisation correcte")
    #     else:
    #         print("✗ ERREUR: Donnees ou CRC incorrect")
    # else:
    #     print("✗ ERREUR: Deserialisation a echoue")
    
    # # Test avec un ACK
    # print("\nTest avec ACK:")
    # ack = Trame(num_seq=10, data=b'', type_trame=TYPE_ACK)
    # ack_bytes = ack.serialiser()
    # print(f"ACK serialise: {len(ack_bytes)} octets")
    
    # ack_recu, crc_ok = Trame.deserialiser(ack_bytes)
    # if ack_recu is not None and crc_ok:
    #     print(f"✓ ACK deserialise: num_seq={ack_recu.num_seq}, type={ack_recu.type_trame}")
    # else:
    #     print("✗ ERREUR: ACK invalide")
    
    
    # # ========================================================================
    # # TEST 3: Corruption de trame
    # # ========================================================================
    # print("\n>>> TEST 3: Detection d'erreur (CRC)")
    # print("-" * 70)
    
    # trame_ok = Trame(3, b"Data", TYPE_DATA)
    # trame_ok_bytes = trame_ok.serialiser()
    # print(f"Trame correcte: {trame_ok_bytes.hex()}")
    
    # # Corrompre 1 bit
    # trame_corrompue = bytearray(trame_ok_bytes)
    # trame_corrompue[5] = trame_corrompue[5] ^ 0x01  # Inverser 1 bit
    # trame_corrompue = bytes(trame_corrompue)
    # print(f"Trame corrompue: {trame_corrompue.hex()}")
    
    # # Tester detection
    # trame_test, crc_valide = Trame.deserialiser(trame_corrompue)
    # if not crc_valide:
    #     print("✓ Erreur detectee par le CRC")
    # else:
    #     print("✗ ERREUR: Corruption non detectee!")
    
    
    # # ========================================================================
    # # TEST 4: Canal
    # # ========================================================================
    # print("\n>>> TEST 4: Canal de transmission")
    # print("-" * 70)
    
    # canal_test = Canal(probErreur=0.3, probPerte=0.2, delaiMax=0.05)
    # print("Canal cree avec: erreur=0.3, perte=0.2, delai=50ms")
    
    # print("\nEnvoi de 10 trames de test:")
    # for i in range(10):
    #     trame = f"Trame_{i}".encode()
    #     resultat = canal_test.transmettre(trame)
        
    #     if resultat is None:
    #         print(f"  #{i}: PERDUE")
    #     elif resultat != trame:
    #         print(f"  #{i}: CORROMPUE")
    #     else:
    #         print(f"  #{i}: OK")
    
    # stats = canal_test.get_statistiques()
    # print(f"\nStatistiques:")
    # print(f"  Transmises: {stats['transmises']}")
    # print(f"  Perdues:    {stats['perdues']}")
    # print(f"  Corrompues: {stats['corrompues']}")
    
    # if stats['transmises'] > 0 or stats['perdues'] > 0:
    #     print("✓ Canal fonctionne")
    # else:
    #     print("✗ ERREUR: Canal ne transmet rien")
    
    
    # # ========================================================================
    # # TEST 5: Emetteur - Segmentation
    # # ========================================================================
    # print("\n>>> TEST 5: Segmentation du message")
    # print("-" * 70)
    
    # canal_seg = Canal(probErreur=0, probPerte=0, delaiMax=0.01)
    # emetteur_test = Emetteur(canal_seg)
    
    # # Message de test
    # message_test = b"A" * 250  # 250 octets
    # print(f"Message test: {len(message_test)} octets")
    
    # chunks = emetteur_test._segmenter(message_test)
    # print(f"Segmente en {len(chunks)} trames")
    
    # for i, chunk in enumerate(chunks):
    #     print(f"  Trame {i}: {len(chunk)} octets")
    
    # # Verifier
    # total = sum(len(c) for c in chunks)
    # if total == len(message_test):
    #     print(f"✓ Segmentation correcte: {total} octets au total")
    # else:
    #     print(f"✗ ERREUR: {total} octets != {len(message_test)}")
    
    
    # # ========================================================================
    # # TEST 6: Recepteur - Recomposition
    # # ========================================================================
    # print("\n>>> TEST 6: Recomposition du message")
    # print("-" * 70)
    
    # canal_rec = Canal(probErreur=0, probPerte=0, delaiMax=0.01)
    # recepteur_test = Recepteur(canal_rec)
    
    # # Simuler reception de 3 trames
    # recepteur_test.trames_recues = [
    #     (0, b"Hello"),
    #     (1, b"World"),
    #     (2, b"!")
    # ]
    # recepteur_test.dernier_num_seq = 2
    
    # message_recompose = recepteur_test.recomposer_message()
    # print(f"Message recompose: {message_recompose}")
    
    # if message_recompose == b"HelloWorld!":
    #     print("✓ Recomposition correcte")
    # else:
    #     print("✗ ERREUR: Recomposition incorrecte")
    
    
    # # ========================================================================
    # # TEST 7: Transmission simple (3 trames)
    # # ========================================================================
    # print("\n>>> TEST 7: Transmission simple (3 trames)")
    # print("-" * 70)
    
    # canal_simple = Canal(probErreur=0.0, probPerte=0.0, delaiMax=0.05)
    # emetteur_simple = Emetteur(canal_simple)
    # recepteur_simple = Recepteur(canal_simple)
    
    # trames_test = [b"AAA", b"BBB", b"CCC"]
    
    # print("Envoi de 3 trames:\n")
    # for i, data in enumerate(trames_test):
    #     # Emetteur cree et envoie
    #     trame = Trame(i, data, TYPE_DATA)
    #     trame_bytes = trame.serialiser()
    #     print(f"[{get_timestamp()}] Envoi trame #{i}: {data}")
        
    #     # Transmettre via canal
    #     trame_transmise = canal_simple.transmettre(trame_bytes)
        
    #     # Recepteur recoit
    #     if trame_transmise is not None:
    #         trame_recue, crc_ok = Trame.deserialiser(trame_transmise)
            
    #         if crc_ok and trame_recue.num_seq == recepteur_simple.dernier_num_seq + 1:
    #             recepteur_simple.trames_recues.append((i, trame_recue.data))
    #             recepteur_simple.dernier_num_seq = i
    #             print(f"[{get_timestamp()}] Recu trame #{i}: CRC OK\n")
    #         else:
    #             print(f"[{get_timestamp()}] Trame #{i}: CRC ERREUR\n")
    #     else:
    #         print(f"[{get_timestamp()}] Trame #{i}: PERDUE\n")
    
    # # Verifier
    # message_final = recepteur_simple.recomposer_message()
    # print(f"Message final: {message_final}")
    
    # if message_final == b"AAABBBCCC":
    #     print("✓ Transmission simple reussie")
    # else:
    #     print("✗ ERREUR: Message incorrect")

    # --- Test: transmit message.txt from repo root ---
    print("\n>>> TEST 8: Transmission du fichier message.txt")
    print("-" * 70)
    fichier_message = '../message.txt'
    result = simulation_gobackn(fichier_message, probErreur=0.1, probPerte=0.05, delaiMax=0.05)
    print("\nTest result:", result)

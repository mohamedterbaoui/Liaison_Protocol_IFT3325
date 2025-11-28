import time
import struct
from datetime import datetime
from stuffing import bit_stuffing, bit_destuffing, ajouter_flags, extraire_entre_flags
from canal import Canal



TAILLE_MAX_DATA = 100  # Taille maximale des donnees par trame (octets)
TIMEOUT = 0.250         # Timeout en secondes (250ms)

# Types de trames
TYPE_DATA = 0
TYPE_ACK = 1

def calculer_crc16(data):
    # Calcule le CRC-16 CCITT (polynome 0x1021)
    # Utilisation de la methode de verification 'reste = 0'
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
    # Justification dans le rapport

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
        # Segmente le message en chunks de TAILLE_MAX_DATA octets
        # retourne liste de bytes (chaque element = 1 trame de donnees)
 
        chunks = []
        
        # Parcourir le message par blocs de TAILLE_MAX_DATA
        for i in range(0, len(message), TAILLE_MAX_DATA):
            # Extraire un chunk
            chunk = message[i:i+TAILLE_MAX_DATA]
            chunks.append(chunk)
        
        return chunks
    
    
class Recepteur:
    # Recepteur de trames
    # Verifie le CRC, envoie les ACKs, recompose le message
    
    def __init__(self, canal):
        # Constructeur du recepteur

        self.canal = canal
        
        # Liste pour stocker les trames recues: (num_seq, data)
        self.trames_recues = []
        
        # Dernier numero de sequence recu correctement
        self.dernier_num_seq = -1
        
        # Statistiques
        self.trames_acceptees = 0
        self.trames_rejetees = 0
        self.acks_envoyes = 0
    
    def recomposer_message(self):
        # Recompose le message complet a partir des trames recues

        # Trier par numero de sequence (normalement deja dans l'ordre)
        self.trames_recues.sort(key=lambda x: x[0])
        
        # Concatener toutes les donnees
        message = b''
        for num_seq, data in self.trames_recues:
            message = message + data
        
        return message
    

def simulation_gobackn(fichier_path, probErreur=0.05, probPerte=0.10, delaiMax=0.02,
                       timeout=TIMEOUT, taille_fenetre=5, max_tentatives=5):
    # Simulation GO-BACK-N
    # - Ne modifie pas le Canal.
    # - Introduit un buffer global d'ACKs pour ne pas "perdre" les ACKs arrivant hors timing.
    # - Mesure le temps d'envoi réel (send_times) et déclenche timeout si elapsed > timeout.

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
    base_emetteur = 0  # indice de la plus ancienne trame non acquittée
    tentatives = [0] * nb_trames_total
    # send_times stocke l'instant d'envoi (time.time()) pour chaque trame envoyée/retx,
    # ou None si pas en attente.
    send_times = [None] * nb_trames_total
    temps_debut = time.time()

    # Buffer global pour ACKs reçus
    acks_buffer_global = set()
    
    print("Debut transmission...\n")

    # Fonction pouyr retransmettre toutes les trames de la fenêtre à partir de base
    def retransmettre_depuis_base():
        print(f"[{get_timestamp()}] 🔁 GO-BACK-N: Retransmission depuis base={base_emetteur} jusqu'à {fin_fenetre - 1}")
        for num_seq in range(base_emetteur, fin_fenetre):
            data = trames_data[num_seq]
            trame = Trame(num_seq, data, TYPE_DATA)
            trame_bytes = trame.serialiser()

            print(f"[{get_timestamp()}] 🔄 RETRANS trame #{num_seq}")
            emetteur.trames_retransmises += 1
            tentatives[num_seq] += 1
            send_times[num_seq] = time.time()

            # Transmettre la trame
            trame_transmise = canal.transmettre(trame_bytes)
            if trame_transmise is None:
                print(f"[{get_timestamp()}]   ❌ Trame PERDUE dans canal (retransmission)")
                # on continue à tenter les suivantes; le timeout re-déclenchera si nécessaire
                continue

            # Réception côté récepteur
            trame_recue, crc_valide = Trame.deserialiser(trame_transmise)
            if not crc_valide:
                print(f"[{get_timestamp()}]   ❌ Trame CORROMPUE (CRC) en retransmission")
                recepteur.trames_rejetees += 1
                continue

            # Ordonnancement Go-Back-N
            if trame_recue.num_seq == recepteur.dernier_num_seq + 1:
                print(f"[{get_timestamp()}]   ✅ Recepteur accepte trame #{num_seq} (retransmission)")
                recepteur.trames_recues.append((num_seq, data))
                recepteur.dernier_num_seq = num_seq
                recepteur.trames_acceptees += 1

                # Envoyer ACK
                ack = Trame(num_seq, b'', TYPE_ACK)
                ack_bytes = ack.serialiser()
                print(f"[{get_timestamp()}]   📨 Recepteur envoie ACK #{num_seq} (retransmission)")
                ack_transmis = canal.transmettre(ack_bytes)
                recepteur.acks_envoyes += 1
                time.sleep(delaiMax)

                if ack_transmis is not None:
                    print(f"[{get_timestamp()}]   ✅ Emetteur recoit ACK #{num_seq}")
                    emetteur.acks_recus += 1
                    # ACK cumulatif: on marque toutes les trames <= num_seq comme acquittées
                    for k in range(base_emetteur, num_seq + 1):
                        acks_recus_cette_fenetre.add(k)
                        acks_buffer_global.add(k)
                        send_times[k] = None
                else:
                    print(f"[{get_timestamp()}]   ❌ ACK #{num_seq} PERDU dans canal")
                    break
            else:
                # Duplicata/hors ordre → ACK du dernier reçu (utile pour débloquer la base)
                print(
                    f"[{get_timestamp()}]   ⚠️  Trame #{num_seq} hors ordre (retransmission), recepteur attend #{recepteur.dernier_num_seq + 1}")
                recepteur.trames_rejetees += 1
                if recepteur.dernier_num_seq >= 0:
                    ack_dernier = Trame(recepteur.dernier_num_seq, b'', TYPE_ACK)
                    ack_dernier_bytes = ack_dernier.serialiser()
                    print(f"[{get_timestamp()}]   📨 Recepteur renvoie ACK duplicata #{recepteur.dernier_num_seq}")
                    ack_dernier_transmis = canal.transmettre(ack_dernier_bytes)
                    recepteur.acks_envoyes += 1
                    if ack_dernier_transmis is not None:
                        dernier = recepteur.dernier_num_seq
                        print(f"[{get_timestamp()}]   ✅ Emetteur recoit ACK duplicata #{dernier}")
                        emetteur.acks_recus += 1
                        # ACK cumulatif: tout jusqu'à 'dernier' est considéré acquitté
                        for k in range(base_emetteur, dernier + 1):
                            acks_buffer_global.add(k)
                            send_times[k] = None

    # ========================================================================
    # BOUCLE PRINCIPALE
    # ========================================================================
    while base_emetteur < nb_trames_total:
        fin_fenetre = min(base_emetteur + taille_fenetre, nb_trames_total)
        print(f"[{get_timestamp()}] 📊 Fenetre emetteur: [{base_emetteur}, {fin_fenetre-1}], Recepteur attend: #{recepteur.dernier_num_seq + 1}")
        
        # On garde un set local pour debug mais la progression sera faite
        # en se basant sur acks_buffer_global (persistant).
        acks_recus_cette_fenetre = set()
        
        # Si le timer pour la base_emetteur est actif et a expiré, on détecte timeout
        timeout_detecte = False
        if base_emetteur < nb_trames_total and send_times[base_emetteur] is not None:
            elapsed = time.time() - send_times[base_emetteur]
            if elapsed > timeout:
                timeout_detecte = True
                print(f"[{get_timestamp()}] ⏱️  TIMEOUT DETECTE pour base={base_emetteur} (elapsed={elapsed:.3f}s > timeout={timeout:.3f}s)")
        
        # Si timeout déjà détecté avant d'envoyer la fenêtre, on n'envoie rien de nouveau :
        # on passera ensuite à la retransmission (retransmission = renvoi depuis base)
        if timeout_detecte:
            retransmettre_depuis_base()
            # on indique qu'on va retransmettre depuis base (la boucle suivante gèrera les tentatives)
            print(f"[{get_timestamp()}] 🔁 Préparation retransmission GO-BACK-N depuis base={base_emetteur}\n")
        else:
            # Sinon on envoie chaque trame de la fenêtre (ou retransmet individuellement si nécessaire)
            for num_seq in range(base_emetteur, fin_fenetre):
                
                # Verifier tentatives
                if tentatives[num_seq] >= max_tentatives:
                    print(f"[{get_timestamp()}] ❌ ABANDON trame #{num_seq}")
                    # On considère l'abandon comme si on laissait base avancer (perte définitive)
                    # (selon ton comportement précédent)
                    base_emetteur += 1
                    # Nettoyage éventuel du send_times
                    send_times[num_seq] = None
                    continue
                
                # Si on a déjà envoyé la trame et qu'on attend l'ACK,
                # on n'a pas besoin de la renvoyer sauf si c'est une retransmission explicitement.
                # Dans cette version minimale, on transmet la trame chaque itération de fenêtre
                # *si* send_times[num_seq] is None (jamais envoyée) OU si on est en mode retransmission.
                
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
                
                # Enregistrer l'instant d'envoi (toujours mettre à jour à l'envoi/retransmission)
                send_times[num_seq] = time.time()
                
                tentatives[num_seq] += 1
                
                # ============================================================
                # PHASE 1: TRANSMETTRE LA TRAME
                # ============================================================
                trame_transmise = canal.transmettre(trame_bytes)
                
                if trame_transmise is None:
                    print(f"[{get_timestamp()}]   ❌ Trame PERDUE dans canal")
                    # On sort de la boucle d'envoi pour attendre timeout (on laisse send_times tel quel)
                    break
                
                # ============================================================
                # PHASE 2: RECEPTEUR TRAITE LA TRAME
                # ============================================================
                trame_recue, crc_valide = Trame.deserialiser(trame_transmise)
                
                if not crc_valide:
                    print(f"[{get_timestamp()}]   ❌ Trame CORROMPUE (CRC)")
                    recepteur.trames_rejetees += 1
                    # Recepteur ne fait rien, pas d'ACK; on sort pour attendre timeout
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
                    
                    # Transmettre l'ACK via le canal — on récupère le résultat
                    ack_transmis = canal.transmettre(ack_bytes)
                    recepteur.acks_envoyes += 1
                    # petite attente simulée côté récepteur
                    time.sleep(0.01)
                    
                    # ============================================================
                    # PHASE 3: EMETTEUR RECOIT (ou pas) L'ACK
                    # ============================================================
                    if ack_transmis is not None:
                        # ACK arrive a l'emetteur : on le stocke dans le buffer global
                        print(f"[{get_timestamp()}]   ✅ Emetteur recoit ACK #{num_seq}")
                        emetteur.acks_recus += 1
                        for k in range(base_emetteur, num_seq + 1):
                            acks_recus_cette_fenetre.add(k)
                            acks_buffer_global.add(k)
                            send_times[k] = None

                    else:
                        # ACK perdu
                        print(f"[{get_timestamp()}]   ❌ ACK #{num_seq} PERDU dans canal")
                        # On ne fait pas break ici autrement que pour sortir de la boucle et
                        # attendre timeout : l'ACK manquant fera timeout plus tard.
                        break
                
                else:
                    # Trame hors ordre (duplicata ou saut)
                    print(f"[{get_timestamp()}]   ⚠️  Trame #{num_seq} hors ordre (recepteur attend #{recepteur.dernier_num_seq + 1})")
                    recepteur.trames_rejetees += 1
                    
                    # Go-Back-N: Recepteur renvoie ACK du dernier recu (si existant)
                    if recepteur.dernier_num_seq >= 0:
                        ack_dernier = Trame(recepteur.dernier_num_seq, b'', TYPE_ACK)
                        ack_dernier_bytes = ack_dernier.serialiser()
                        print(f"[{get_timestamp()}]   📨 Recepteur renvoie ACK #{recepteur.dernier_num_seq} (duplicata)")
                        # ici on récupère aussi la livraison de l'ACK duplicata
                        ack_dernier_transmis = canal.transmettre(ack_dernier_bytes)
                        recepteur.acks_envoyes += 1
                        # si l'ACK duplicata parvient, le conserver dans le buffer global
                        if ack_dernier_transmis is not None:
                            dernier = recepteur.dernier_num_seq
                            print(f"[{get_timestamp()}]   ✅ Emetteur recoit ACK duplicata #{dernier}")
                            emetteur.acks_recus += 1
                            # ACK cumulatif: tout jusqu'à 'dernier' est considéré acquitté
                            for k in range(base_emetteur, dernier + 1):
                                acks_buffer_global.add(k)
                                send_times[k] = None
                    
                    # Arreter l'envoi de cette fenetre (on sort pour traiter acks / timeout)
                    break
        
        # ----------------------------------------------------------------
        # AVANCER BASE EMETTEUR en se basant sur acks_buffer_global
        # ----------------------------------------------------------------
        ancien_base = base_emetteur
        
        while base_emetteur in acks_buffer_global:
            # On consomme l'ACK et on annule le timer de la trame acquittée (déjà fait plus haut)
            base_emetteur += 1
        
        # Nettoyer le buffer
        acks_buffer_global = {a for a in acks_buffer_global if a >= base_emetteur}
        
        if base_emetteur > ancien_base:
            print(f"[{get_timestamp()}] 📊 Base emetteur avance: {ancien_base} → {base_emetteur}\n")
            # Si la base a avancé, on continue (les send_times pour les trames acquittées sont None)
            # et la prochaine itération enverra/retx suivant la logique.
        else:
            # Aucune progression : vérifier si timeout réel s'est produit pour la base
            timeout_actuel = False
            if base_emetteur < nb_trames_total and send_times[base_emetteur] is not None:
                elapsed_base = time.time() - send_times[base_emetteur]
                if elapsed_base > timeout:
                    timeout_actuel = True
                    print(f"[{get_timestamp()}] ⏱️  TIMEOUT: Aucun ACK utile recu pour base={base_emetteur} (elapsed={elapsed_base:.3f}s > timeout={timeout:.3f}s). GO-BACK-N depuis base={base_emetteur}\n")
            
            if not timeout_actuel:
                # Aucun ACK utile reçu et pas (encore) de timeout : attente courte
                # On laisse un petit délai pour simuler l'attente de réponses asynchrones
                time.sleep(0.01)
            else:
                # Timeout détecté → retransmission immédiate depuis la base
                retransmettre_depuis_base()
                # Petite pause pour éviter le busy-wait
                time.sleep(timeout * 0.1)
        
        # Petit sleep pour laisser "respirer" la simulation
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
    #     print(" CRCs differents pour donnees differentes")
    # else:
    #     print(" ERREUR: CRCs identiques!")
    
    # # Test verification reste = 0
    # print("\nTest verification 'reste = 0':")
    # trame_test = data1 + struct.pack('!H', crc1)
    # reste = calculer_crc16(trame_test)
    # print(f"Reste pour (data + CRC): {reste}")
    # if reste == 0:
    #     print(" Reste = 0 (verification correcte)")
    # else:
    #     print(" ERREUR: Reste != 0")
    
    
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
    #         print(" Serialisation/Deserialisation correcte")
    #     else:
    #         print(" ERREUR: Donnees ou CRC incorrect")
    # else:
    #     print(" ERREUR: Deserialisation a echoue")
    
    # # Test avec un ACK
    # print("\nTest avec ACK:")
    # ack = Trame(num_seq=10, data=b'', type_trame=TYPE_ACK)
    # ack_bytes = ack.serialiser()
    # print(f"ACK serialise: {len(ack_bytes)} octets")
    
    # ack_recu, crc_ok = Trame.deserialiser(ack_bytes)
    # if ack_recu is not None and crc_ok:
    #     print(f" ACK deserialise: num_seq={ack_recu.num_seq}, type={ack_recu.type_trame}")
    # else:
    #     print(" ERREUR: ACK invalide")
    
    
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
    #     print(" Erreur detectee par le CRC")
    # else:
    #     print(" ERREUR: Corruption non detectee!")
    
    # # ========================================================================
    # # TEST 4: Emetteur - Segmentation
    # # ========================================================================
    # print("\n>>> TEST 4: Segmentation du message")
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
    #     print(f" Segmentation correcte: {total} octets au total")
    # else:
    #     print(f" ERREUR: {total} octets != {len(message_test)}")
    
    
    # # ========================================================================
    # # TEST 5: Recepteur - Recomposition
    # # ========================================================================
    # print("\n>>> TEST 5: Recomposition du message")
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
    #     print(" Recomposition correcte")
    # else:
    #     print(" ERREUR: Recomposition incorrecte")
    
    
    # # ========================================================================
    # # TEST 6: Transmission simple (3 trames)
    # # ========================================================================
    # print("\n>>> TEST 6: Transmission simple (3 trames)")
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
    #     print(" Transmission simple reussie")
    # else:
    #     print(" ERREUR: Message incorrect")


    # ========================================================================
    # TEST 7: transmission de "message.txt" + Influence du délai sur les temporisations
    # ========================================================================
    print("\n>>> TEST 7: Influence du délai sur les temporisations")
    print("-" * 70)
    fichier_message = '../message.txt'

    # Cas 1 : delaiMax = 50 ms (< timeout)
    print("\nCas 1: delaiMax = 0.050 s (< timeout, aucune retransmission attendue)")
    simulation_gobackn(fichier_message, probErreur=0.05, probPerte=0.10,
                       delaiMax=0.050, timeout=0.200)

    # Cas 2 : delaiMax = 180 ms (≈ timeout)
    print("\nCas 2: delaiMax = 0.180 s (≈ timeout, quelques faux timeouts attendus)")
    simulation_gobackn(fichier_message, probErreur=0.05, probPerte=0.10,
                       delaiMax=0.180, timeout=0.200)

    # Cas 3 : delaiMax = 300 ms (> timeout)
    print("\nCas 3: delaiMax = 0.300 s (> timeout, nombreuses retransmissions attendues)")
    simulation_gobackn(fichier_message, probErreur=0.05, probPerte=0.10,
                       delaiMax=0.300, timeout=0.200)

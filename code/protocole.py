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
    # Calculer le CRC 16 bits
    crc = 0xFFFF  # Valeur initiale (tous les bits a 1)
    
    # Parcourir chaque octet des donnees
    for byte in data:
        crc = crc ^ byte  # XOR avec l'octet courant
        
        # Traiter les 8 bits de l'octet
        for i in range(8):
            # Si le bit de poids faible est 1
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001  # Shift right + XOR avec polynome
            else:
                crc = crc >> 1  # Juste shift right
    
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
    
    def _envoyer_trame(self, num_seq, data):
        """
        Envoie UNE trame de donnees via le canal
        
        Args:
            num_seq: numero de sequence
            data: bytes de donnees
        
        Returns:
            bytes de la trame transmise (ou None si perdue)
        """
        # Creer la trame
        trame = Trame(num_seq, data, TYPE_DATA)
        
        # Serialiser (convertir en bytes)
        trame_bytes = trame.serialiser()
        
        # Afficher l'evenement
        print(f"[{get_timestamp()}] Envoi trame #{num_seq} ({len(data)} octets)")
        
        # Incrementer le compteur
        self.trames_envoyees = self.trames_envoyees + 1
        
        # Transmettre via le canal
        trame_transmise = self.canal.transmettre(trame_bytes)
        
        return trame_transmise
    
    def envoyer_message(self, fichier_path):
        """
        Envoie un fichier complet
        VERSION SIMPLIFIEE (sans retransmission pour l'instant)
        
        Args:
            fichier_path: chemin du fichier a transmettre
        
        Returns:
            dictionnaire avec statistiques
        """
        print(f"\n{'='*60}")
        print(f"DEBUT DE LA TRANSMISSION")
        print(f"Fichier: {fichier_path}")
        print(f"{'='*60}\n")
        
        # Lire le fichier
        with open(fichier_path, 'rb') as f:
            message = f.read()
        
        print(f"Taille du fichier: {len(message)} octets")
        
        # Segmenter en trames
        trames_data = self._segmenter(message)
        print(f"Segmente en {len(trames_data)} trames\n")
        
        # Enregistrer le temps de debut
        temps_debut = time.time()
        
        # Envoyer chaque trame (sans gestion des erreurs pour l'instant)
        for i in range(len(trames_data)):
            data = trames_data[i]
            
            # Envoyer la trame
            resultat = self._envoyer_trame(i, data)
            
            # Attendre un peu (simuler ACK - simplifie)
            time.sleep(0.1)
        
        # Calculer la duree
        duree = time.time() - temps_debut
        
        # Afficher les resultats
        print(f"\n{'='*60}")
        print("Transmission terminee.")
        print(f"Frames envoyees : {self.trames_envoyees}")
        print(f"Frames retransmises : {self.trames_retransmises}")
        print(f"ACK recus : {self.acks_recus}")
        print(f"Duree totale : {duree:.2f} s")
        print(f"{'='*60}\n")
        
        # Retourner les stats
        return {
            'envoyees': self.trames_envoyees,
            'retransmises': self.trames_retransmises,
            'acks': self.acks_recus,
            'duree': duree
        }
    
if __name__ == "__main__":
    print("\n=== Test de l'emetteur (version simplifiee) ===\n")
        
    # Creer le canal et l'emetteur
    canal = Canal(probErreur=0.05, probPerte=0.10, delaiMax=0.1)
    emetteur = Emetteur(canal, timeout=0.25, taille_fenetre=5)
        
    # Envoyer le fichier
    stats = emetteur.envoyer_message('../message.txt')
        
    # Afficher stats du canal
    canal.afficher_statistiques()
    

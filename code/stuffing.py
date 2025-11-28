def bit_stuffing(bits_str):

    # Applique le bit-stuffing HDLC: apres 5 bits '1' consecutifs, insere un '0'

    resultat = ""
    compteur_uns = 0
    
    # Parcourir chaque bit de la chaine
    for i in range(len(bits_str)):
        bit = bits_str[i]
        
        # Ajouter le bit au resultat
        resultat = resultat + bit
        
        # Compter les '1' consecutifs
        if bit == '1':
            compteur_uns = compteur_uns + 1
            
            # Si on a 5 '1' consecutifs, inserer un '0'
            if compteur_uns == 5:
                resultat = resultat + '0'  # Inserer le 0
                compteur_uns = 0           # Reinitialiser le compteur
        else:
            # Si on rencontre un '0', reinitialiser le compteur
            compteur_uns = 0
    
    return resultat


def bit_destuffing(bits_str):

    # Retire le bit-stuffing: enleve les '0' inseres apres 5 bits '1' consecutifs

    resultat = ""
    compteur_uns = 0
    i = 0
    
    # Parcourir chaque bit
    while i < len(bits_str):
        bit = bits_str[i]
        
        # Ajouter le bit au resultat
        resultat = resultat + bit
        
        # Compter les '1' consecutifs
        if bit == '1':
            compteur_uns = compteur_uns + 1
            
            # Si on a 5 '1' consecutifs
            if compteur_uns == 5:
                # Le prochain bit est un '0' stuffe, on doit le sauter
                i = i + 1
                # Le bit a la position i est le '0' stuffe, on ne l'ajoute pas
                compteur_uns = 0  # Reinitialiser
        else:
            # Si on rencontre un '0', reinitialiser le compteur
            compteur_uns = 0
        
        i = i + 1  # Passer au bit suivant
    
    return resultat


def ajouter_flags(data_bits):

    #Ajoute les flags HDLC au debut et a la fin des donnees

    FLAG = "01111110"
    
    # FLAG + donnees + FLAG
    trame_complete = FLAG + data_bits + FLAG
    
    return trame_complete


def extraire_entre_flags(trame_bits):

    # Extrait les donnees entre les flags de debut et de fin
    
    FLAG = "01111110"
    
    # Trouver la position du premier FLAG
    position_debut = -1
    for i in range(len(trame_bits) - len(FLAG) + 1):
        if trame_bits[i:i+len(FLAG)] == FLAG:
            position_debut = i
            break
    
    # Si pas de FLAG de debut, retourner None
    if position_debut == -1:
        return None
    
    # Chercher le FLAG de fin (apres le FLAG de debut)
    position_fin = -1
    for i in range(position_debut + len(FLAG), len(trame_bits) - len(FLAG) + 1):
        if trame_bits[i:i+len(FLAG)] == FLAG:
            position_fin = i
            break
    
    # Si pas de FLAG de fin, retourner None
    if position_fin == -1:
        return None
    
    # Extraire les donnees entre les deux FLAGS
    debut_data = position_debut + len(FLAG)
    fin_data = position_fin
    donnees = trame_bits[debut_data:fin_data]
    
    return donnees

def bits_to_bytes(bits_str):
    # Convertit un string de bits en bytes
    # Padding si nécessaire pour avoir un multiple de 8
    if len(bits_str) % 8 != 0:
        bits_str = bits_str + '0' * (8 - len(bits_str) % 8)
    
    # Convertir par blocs de 8 bits
    result = bytearray()
    for i in range(0, len(bits_str), 8):
        byte_str = bits_str[i:i+8]
        result.append(int(byte_str, 2))
    
    return bytes(result)

# Added this function here from protocole.py to test stuffing + CRC because of cyclic imports
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


# Programme principal
if __name__ == "__main__":
    codeWithoutStuffing = "011111101111101111110111110"
    print("Code without stuffing : "+codeWithoutStuffing)

    print("With stuffing: " + bit_stuffing(codeWithoutStuffing))

    print("Add flags : "+ajouter_flags(bit_stuffing(codeWithoutStuffing)))

    print("Extract flags: " + extraire_entre_flags(ajouter_flags(bit_stuffing(codeWithoutStuffing))))

    print("testing destuffing : " + bit_destuffing(extraire_entre_flags(ajouter_flags(bit_stuffing(codeWithoutStuffing)))))

    # ===========================
    # TEST COMPLET AVEC CRC
    # ===========================
    print("\n===== TEST COMPLET: stuffing + CRC + destuffing =====")

    # Données d'origine
    data = b"Bonjour"
    print("Data originale :", data)

    # 1) Convertir en bits
    bits = ''.join(f"{byte:08b}" for byte in data)
    print("Bits :", bits)

    # 2) Calculer CRC sur les données
    crc = calculer_crc16(data)
    print("CRC (hex) :", f"{crc:04X}")

    # 3) Ajouter le CRC à la fin des bits
    bits_crc = bits + f"{crc:016b}"
    print("Bits + CRC :", bits_crc)

    # 4) Bit stuffing
    bits_stuffed = bit_stuffing(bits_crc)
    print("Bits stuffed :", bits_stuffed)

    # 5) Ajouter flags
    trame_bits = ajouter_flags(bits_stuffed)
    print("Bits avec flags :", trame_bits)

    # 6) Extraire entre flags
    extrait = extraire_entre_flags(trame_bits)
    print("Extraite entre flags :", extrait)

    # 7) Destuffing
    bits_destuffed = bit_destuffing(extrait)
    print("Bits destuffed :", bits_destuffed)

    # 8) Reconstruire bytes
    data_recu = bits_to_bytes(bits_destuffed[:-16])  # enlever CRC
    crc_recu = int(bits_destuffed[-16:], 2)

    print("Data reconstruite :", data_recu)
    print("CRC reçu (hex) :", f"{crc_recu:04X}")

    # 9) Vérification CRC (reste = 0)
    # Recalculer le CRC sur data + crc original
    verification = calculer_crc16(data_recu + crc_recu.to_bytes(2, 'big'))

    print("\n=== RESULTAT ===")
    print("CRC valide ?" , verification == 0)
    if verification == 0:
        print(" SUCCESS — Data et CRC intacts après stuffing")
    else:
        print("ERREUR — CRC incorrect après traitement HDLC")

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


# Programme principal
if __name__ == "__main__":    
    codeWithoutStuffing = "0111111"
    print("Code without stuffing : "+codeWithoutStuffing)

    print("With stuffing: " + bit_stuffing(codeWithoutStuffing))

    print("Add flags : "+ajouter_flags(bit_stuffing(codeWithoutStuffing)))

    print("Extract flags: " + extraire_entre_flags(ajouter_flags(bit_stuffing(codeWithoutStuffing))))

    print("testing destuffing : " + bit_destuffing(extraire_entre_flags(ajouter_flags(bit_stuffing(codeWithoutStuffing)))))
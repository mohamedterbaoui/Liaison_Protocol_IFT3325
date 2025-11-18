import random
import time


class Canal:
    # Simule un canal de communication non fiable
    
    def __init__(self, probErreur=0.05, probPerte=0.10, delaiMax=0.2):
        
        self.probErreur = probErreur
        self.probPerte = probPerte
        self.delaiMax = delaiMax
        
        # Compteurs pour les statistiques
        self.trames_transmises = 0
        self.trames_perdues = 0 
        self.trames_corrompues = 0 

    def transmettre(self, data):
        # Simule la transmission d'une trame

        # On simule un delai random, avec un delai maximum
        delai = random.uniform(0, self.delaiMax)
        time.sleep(delai)

        # Simulation de perte de trame
        if random.random() < self.probPerte:
            self.trames_perdues = self.trames_perdues + 1
            return None # car la trame est perdue
        
        # Simulation d'erreur de transmission
        if random.random() < self.probErreur:
            self.trames_corrompues = self.trames_corrompues + 1
            data = self.introduire_erreur(data)
        
        # Transmission reussie
        self.trames_transmises = self.trames_transmises + 1
        return data
    
    def introduire_erreur(self, data):
        # Simule l'introduction d'une erreur au donnees d'une trame
        if len(data) == 0:
            return data
        
        # Convertir bytes en bytearray
        data_array = bytearray(data)
        
        # Choisir un octet aleatoire
        position_byte = random.randint(0, len(data_array) - 1)
        
        # Choisir un bit aleatoire dans cet octet (0 a 7)
        position_bit = random.randint(0, 7)
        
        # Inverser le bit avec XOR
        data_array[position_byte] = data_array[position_byte] ^ (1 << position_bit)
        
        # Reconvertir en bytes
        return bytes(data_array)
    
    def get_statistiques(self):
        stats = {
            'transmises': self.trames_transmises,
            'perdues': self.trames_perdues,
            'corrompues': self.trames_corrompues
        }
        return stats
    
    
    def reset_statistiques(self):
        self.trames_transmises = 0
        self.trames_perdues = 0
        self.trames_corrompues = 0
    
    
    def afficher_statistiques(self):

        print("\n" + "-" * 60)
        print("STATISTIQUES DU CANAL")
        print("-" * 60)
        print(f"Trames transmises avec succes : {self.trames_transmises}")
        print(f"Trames perdues                : {self.trames_perdues}")
        print(f"Trames corrompues             : {self.trames_corrompues}")
        
        total = self.trames_transmises + self.trames_perdues
        if total > 0:
            taux_perte = (self.trames_perdues / total) * 100
            taux_erreur = (self.trames_corrompues / total) * 100
            print(f"\nTaux de perte   : {taux_perte:.2f}%")
            print(f"Taux d'erreur   : {taux_erreur:.2f}%")
        
        print("=" * 60 + "\n")

if __name__ == "__main__":
    # Test 1: Canal avec probabilites moyennes
    print("\n--- Test 1: Canal bruite (probErreur=0.3, probPerte=0.2) ---")
    canal = Canal(probErreur=0.3, probPerte=0.2, delaiMax=0.1)
    
    print("\nEnvoi de 20 trames...")
    for i in range(20):
        trame = f"Trame_{i}".encode()
        
        resultat = canal.transmettre(trame)
        
        if resultat is None:
            print(f"  Trame {i:2d}: PERDUE")
        elif resultat != trame:
            print(f"  Trame {i:2d}: CORROMPUE")
        else:
            print(f"  Trame {i:2d}: OK")
    
    canal.afficher_statistiques()
    
    
    # Test 2: Canal parfait
    print("\n--- Test 2: Canal parfait (aucune erreur) ---")
    canal_parfait = Canal(probErreur=0.0, probPerte=0.0, delaiMax=0.05)
    
    print("\nEnvoi de 20 trames...")
    for i in range(20):
        trame = f"Trame_{i}".encode()
        
        resultat = canal_parfait.transmettre(trame)
        
        if resultat is None:
            print(f"  Trame {i:2d}: PERDUE")
        elif resultat != trame:
            print(f"  Trame {i:2d}: CORROMPUE")
        else:
            print(f"  Trame {i:2d}: OK")
    
    canal_parfait.afficher_statistiques()
    
    
    # Test 3: Canal tres instable
    print("\n--- Test 3: Canal instable (probErreur=0.5, probPerte=0.5) ---")
    canal_instable = Canal(probErreur=0.5, probPerte=0.5, delaiMax=0.2)
    
    print("\nEnvoi de 20 trames...")
    for i in range(20):
        trame = f"Trame_{i}".encode()
        
        resultat = canal_instable.transmettre(trame)
        
        if resultat is None:
            print(f"  Trame {i:2d}: PERDUE")
        elif resultat != trame:
            print(f"  Trame {i:2d}: CORROMPUE")
        else:
            print(f"  Trame {i:2d}: OK")
    
    canal_instable.afficher_statistiques()
    
    # Test 4: tester la fonction d'introduction d'erreur
    trame = f"Trame".encode()
    print("Trame initiale: ")
    print(trame)

    trame_corrompue = canal.introduire_erreur(trame)
    print("Trame corrompue: ")
    print(trame_corrompue)
# Daikin Local - Home Assistant Integration

Une intégration personnalisée pour Home Assistant permettant de contrôler localement les climatiseurs Daikin via leur API locale. Cette solution privilégie la rapidité, la fiabilité et le respect de la vie privée en évitant le passage par le cloud.

## ✨ Caractéristiques

- **Contrôle Climatique complet** : Mode (Chaud, Froid, Sec, Auto, Ventilateur), température cible, vitesse du ventilateur et oscillation.
- **Gestion des Zones** : Support complet des systèmes gainables avec gestion individuelle des zones (marche/arrêt et température si supporté).
- **Capteurs en temps réel** : Températures intérieure/extérieure, humidité et consommation d'énergie (selon le modèle).
- **Fonctions Avancées** : Support du mode Streamer, modes Puissant (Boost) et Éco.
- **Réactivité Immédiate** : Mise à jour instantanée de l'état dans l'interface après chaque changement de paramètre (plus besoin d'attendre le cycle de rafraîchissement de 30s).

## 🚀 Installation

### Via HACS (Recommandé)

1. Ouvrez HACS dans Home Assistant.
2. Cliquez sur les trois points en haut à droite et choisissez **Dépôts personnalisés**.
3. Ajoutez l'URL de ce dépôt avec la catégorie **Intégration**.
4. Recherchez "Daikin Local" et cliquez sur **Télécharger**.
5. Redémarrez Home Assistant.

### Manuelle

1. Téléchargez le dossier `custom_components/daikin_local`.
2. Copiez-le dans le répertoire `custom_components` de votre installation Home Assistant.
3. Redémarrez Home Assistant.

## ⚙️ Configuration

1. Allez dans **Paramètres** > **Appareils et services**.
2. Cliquez sur **Ajouter une intégration**.
3. Recherchez **Daikin Local**.
4. Entrez l'adresse IP de votre unité Daikin.
   - *Note : Il est fortement recommandé de fixer l'IP de votre climatiseur via votre routeur.*

## 🛠️ Développement & Support

Cette intégration utilise la bibliothèque `pydaikin` pour communiquer avec les appareils. Elle est optimisée pour être entièrement asynchrone afin de ne jamais bloquer le processus principal de Home Assistant.

### Pourquoi Daikin Local ?
Contrairement à l'intégration officielle qui peut parfois être limitée ou dépendante du matériel, cette version a été conçue pour offrir une meilleure réactivité et un support étendu des fonctionnalités spécifiques comme les zones et les modes avancés.

---
*Développé avec ❤️ pour la communauté Home Assistant.*

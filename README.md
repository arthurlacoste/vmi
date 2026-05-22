# Video Memory Indexer

Pipeline cron/Python pour exporter les vidéos Photos iCloud puis générer des transcriptions.

## Installation

```bash
cd ~/dev/vmi
brew install ffmpeg pipx
pipx install osxphotos
./install.sh
```

Dans Photos.app, active idéalement : Réglages > iCloud > Télécharger les originaux sur ce Mac.

## Lancement manuel

```bash
cd ~/dev/vmi
./run.sh
```

## Cron

```bash
crontab -e
```

Ajoute :

```cron
0 8-23 * * * cd ~/dev/vmi && ./run.sh >> data/logs/cron.log 2>&1
```

## Sorties

- Vidéos exportées : `data/incoming`
- Copies de travail : `data/processed`
- Audio extrait : `data/audio`
- Transcriptions : `data/transcripts`
- État SQLite : `state/transcriber.sqlite3`

## Notes

`open -a Photos` est utilisé pour réveiller la synchro iCloud Photos. macOS n’a pas de commande officielle qui force réellement iCloud Photos à télécharger immédiatement tous les originaux. `osxphotos --download-missing` aide à demander les fichiers manquants.

La prochaine étape pour les shorts consistera à exploiter les JSON horodatés dans `data/transcripts` pour scorer les segments et produire une liste de highlights candidats.

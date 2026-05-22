# Plan : recherche vidéo, métadonnées et sélection de shorts viraux

## Objectif

Mettre en place deux fonctionnalités au-dessus du pipeline actuel de transcription :

1. Chercher par mots clés dans le contenu parlé des vidéos, ainsi que dans les métadonnées spécifiques des vidéos.
2. Sélectionner automatiquement, dans une vidéo donnée, des moments qui peuvent devenir des shorts viraux, avec timecode de début et de fin, puis préparer un export de découpe utilisable dans DaVinci Resolve ou Final Cut Pro XML.

Pipeline résumé :

```text
1. Sélection d'une vidéo
2. Lancement d'un prompt via Chrome : http://chatgpt.com/?prompt=...
3. Le prompt demande à ChatGPT d'utiliser MCP DL
4. ChatGPT lit la transcription et le JSON de référence local
5. ChatGPT sélectionne les meilleurs moments
6. ChatGPT génère un plan de cut et, ensuite, un export XML
```

## État actuel du projet

Le projet sait déjà :

- scanner iCloud Photos sur les dernières 24h
- scanner toute la base avec `--all`
- limiter le nombre de vidéos éligibles avec `--max N`
- éviter les doublons via UUID Photos et SHA256
- ignorer les vidéos de moins de 30 secondes
- ignorer les vidéos sans audio
- transcrire en français avec Whisper
- générer JSON, TXT et SRT
- enrichir les JSON avec `ffprobe`, `exiftool` si disponible, et les métadonnées `osxphotos`
- scanner des dossiers et fichiers manuels

## Fonctionnalité 1 : recherche texte et métadonnées

### Besoin

Pouvoir chercher des vidéos par :

- mots prononcés dans la transcription
- personnes reconnues par Photos
- labels Apple Photos, par exemple animal, tattoo, outdoor
- lieu GPS ou nom de lieu
- date ou période
- appareil utilisé
- albums
- favoris
- durée
- orientation ou dimensions
- codec/fps
- nom de fichier

Exemples de requêtes :

```bash
./run.sh --search "chat"
./run.sh --search "tattoo" --metadata
./run.sh --search "person animal" --all-fields
./run.sh --where "duration > 120 and device_model contains 'iPhone'"
./run.sh --near 45.04 3.88 --radius-km 2
```

### Stockage recommandé

Ajouter une base SQLite dédiée ou enrichir la base existante :

```text
state/transcriber.sqlite3
```

Tables proposées :

```sql
videos(
  source_id TEXT PRIMARY KEY,
  source_kind TEXT,
  sha256 TEXT,
  filename TEXT,
  source_path TEXT,
  transcript_json TEXT,
  transcript_txt TEXT,
  transcript_srt TEXT,
  duration_seconds REAL,
  created_at TEXT,
  transcribed_at TEXT,
  status TEXT
)

video_metadata(
  source_id TEXT PRIMARY KEY,
  metadata_json TEXT,
  metadata_summary_json TEXT,
  date_original TEXT,
  device_make TEXT,
  device_model TEXT,
  latitude REAL,
  longitude REAL,
  place TEXT,
  labels_text TEXT,
  persons_text TEXT,
  albums_text TEXT,
  keywords_text TEXT,
  ai_caption TEXT,
  width INTEGER,
  height INTEGER,
  fps REAL
)

transcript_segments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT,
  start REAL,
  end REAL,
  text TEXT
)
```

Ajouter ensuite un index FTS5 :

```sql
CREATE VIRTUAL TABLE search_index USING fts5(
  source_id UNINDEXED,
  filename,
  transcript,
  segments,
  labels,
  persons,
  albums,
  keywords,
  place,
  ai_caption,
  metadata
);
```

### Commandes CLI proposées

Indexer ou réindexer :

```bash
./run.sh --index
./run.sh --reindex
```

Chercher :

```bash
./run.sh --search "animal"
./run.sh --search "tattoo" --limit 20
./run.sh --search "person" --field persons
./run.sh --search "vacances montagne" --json
```

Ouvrir le JSON d'une vidéo :

```bash
./run.sh --show <source_id>
```

Préparer une vidéo pour sélection de shorts :

```bash
./run.sh --select-video <source_id>
```

### Format de sortie de recherche

Sortie humaine :

```text
1. IMG_5366.MOV
   source_id: 69BD9190-04FB-471E-BC13-86A54B500F4C
   duration: 87.4s
   labels: Art, Tattoo
   persons: Person
   match: "... texte autour du mot trouvé ..."
   transcript_json: data/transcripts/IMG_5366_xxx.json
```

Sortie JSON :

```json
{
  "query": "tattoo",
  "results": [
    {
      "source_id": "...",
      "filename": "IMG_5366.MOV",
      "duration": 87.4,
      "score": 12.3,
      "matches": [
        {
          "field": "labels",
          "value": "Tattoo"
        }
      ],
      "transcript_json": "..."
    }
  ]
}
```

## Fonctionnalité 2 : sélection de moments viraux

### Besoin

À partir d'une transcription JSON horodatée, identifier des moments courts qui ont un potentiel viral.

Critères possibles :

- phrase d'accroche forte dans les 2 premières secondes
- surprise, tension, contradiction, émotion, révélation
- moment drôle, absurde ou très clair
- séquence compréhensible hors contexte
- durée adaptée à un short, par exemple 12 à 45 secondes
- segment avec début et fin propres
- possibilité de créer un titre ou hook à l'écran
- densité de parole suffisante
- éviter les passages confus, trop longs, sans chute ou trop dépendants du contexte

### Sortie attendue

Le modèle doit produire une liste de candidats :

```json
{
  "video": {
    "source_id": "...",
    "filename": "...",
    "transcript_json": "..."
  },
  "candidates": [
    {
      "rank": 1,
      "title": "Hook proposé",
      "start": 123.4,
      "end": 154.2,
      "duration": 30.8,
      "score": 91,
      "reason": "Pourquoi ce moment peut marcher",
      "hook_text": "Phrase d'accroche à afficher",
      "caption": "Description courte",
      "cut_notes": "Couper juste avant la respiration, garder la chute finale",
      "risks": ["dépend un peu du contexte"],
      "source_segments": [12, 13, 14]
    }
  ]
}
```

### Export de découpe

Dans un premier temps, générer un format neutre interne :

```json
{
  "timeline": {
    "name": "short_candidates_IMG_5366",
    "source_video": "/path/to/source.mov",
    "clips": [
      {
        "name": "candidate_01",
        "source_start": 123.4,
        "source_end": 154.2,
        "timeline_start": 0,
        "timeline_end": 30.8
      }
    ]
  }
}
```

Ensuite, convertir ce format vers :

- FCPXML pour Final Cut Pro
- OTIO, OpenTimelineIO, si on veut une passerelle vers DaVinci
- EDL simple pour compatibilité minimale
- DaVinci Resolve scripting Python, si Resolve est installé localement

Recommandation : commencer par FCPXML + JSON interne. FCPXML est lisible, versionnable, et suffisant pour tester des cuts.

## Prompt ChatGPT via Chrome

### Approche recommandée

Ne pas mettre toute la logique dans l'URL `prompt=`.

L'URL doit contenir un prompt court qui pointe vers :

- un fichier local de directives versionné
- le JSON de transcription
- le fichier vidéo source si disponible
- le dossier de sortie attendu

Pourquoi :

- les URLs longues sont fragiles
- les caractères spéciaux cassent facilement l'encodage
- c'est difficile à versionner
- c'est plus dur à améliorer
- un fichier de directives joue mieux le rôle d'un `agents.md`

Donc oui, il vaut mieux créer un fichier de directives, par exemple :

```text
docs/SHORTS_AGENT.md
```

Puis le prompt URL dit simplement :

```text
Utilise MCP DL. Lis les directives dans ~/dev/vmi/docs/SHORTS_AGENT.md. Analyse la transcription JSON suivante : <path>. Produis les candidats viraux et crée un export de cut XML dans <output_dir>.
```

### Exemple d'URL

Le script local générera une URL encodée :

```bash
open -a "Google Chrome" "https://chatgpt.com/?prompt=..."
```

Exemple de prompt brut avant encodage :

```text
Utilise MCP DL pour lire les fichiers locaux.
Lis d'abord les directives : ~/dev/vmi/docs/SHORTS_AGENT.md
Analyse cette transcription JSON : ~/dev/vmi/data/transcripts/IMG_5366_xxx.json
Utilise le fichier vidéo source si disponible : /path/to/source.mov
Crée un fichier de sélection JSON et un export FCPXML dans : ~/dev/vmi/data/exports/IMG_5366_xxx/
Objectif : sélectionner les meilleurs moments viraux pour shorts avec timecodes début/fin.
```

## Fichier de directives agent

Créer :

```text
docs/SHORTS_AGENT.md
```

Contenu proposé :

```md
# Shorts Agent

Tu es un assistant de sélection éditoriale pour shorts verticaux.

## Entrées

Tu reçois :
- un JSON de transcription horodatée
- des métadonnées vidéo
- éventuellement un chemin vers le fichier vidéo source
- un dossier de sortie

## Objectif

Identifier les meilleurs extraits courts pouvant devenir des shorts viraux.

## Critères de sélection

Priorise :
- hook clair dès le début
- tension, surprise, contradiction ou révélation
- émotion ou humour
- passage compréhensible sans contexte
- durée cible 12 à 45 secondes
- phrase de fin satisfaisante
- montage possible sans casser le sens

Évite :
- extraits trop longs
- passages sans chute
- phrases incomplètes
- références trop dépendantes du contexte
- passages pauvres en parole

## Sortie obligatoire

Crée :

1. `viral_candidates.json`
2. `viral_candidates.md`
3. `cuts.fcpxml` si possible

## Format JSON

Inclure pour chaque candidat :
- rank
- title
- start
- end
- duration
- score 0-100
- reason
- hook_text
- subtitle_style_note
- cut_notes
- source_segments

## Règles de timecode

- Ne jamais inventer de timecode absent de la transcription.
- Utiliser les timestamps des segments.
- Étendre légèrement le début ou la fin seulement si cela améliore la coupe.
- Garder une marge maximale de 0.5 seconde sauf justification.

## Export XML

Créer un export de découpe basé sur les timecodes sélectionnés.
Si FCPXML exact n'est pas possible, créer d'abord un JSON timeline neutre et expliquer ce qui manque.
```

## Nouveau script proposé : open_short_prompt.py

Ajouter :

```bash
./run.sh --open-short-prompt <source_id>
```

Le script :

1. cherche `source_id` dans SQLite
2. récupère `transcript_json`
3. crée un dossier d'export
4. génère le prompt court
5. encode le prompt
6. ouvre Chrome sur `https://chatgpt.com/?prompt=...`

Pseudo-code :

```python
from urllib.parse import quote
import subprocess

prompt = f"""
Utilise MCP DL pour lire les fichiers locaux.
Lis les directives : {agent_file}
Analyse cette transcription JSON : {transcript_json}
Crée les sorties dans : {output_dir}
""".strip()

url = "https://chatgpt.com/?prompt=" + quote(prompt)
subprocess.run(["open", "-a", "Google Chrome", url])
```

## Recommandation : fichier directives ou prompt direct ?

Réponse courte : utiliser les deux, mais pas pour le même rôle.

Recommandation :

- `docs/SHORTS_AGENT.md` contient le comportement stable, comme un `agents.md`
- l'URL `prompt=` contient seulement la mission du run, les chemins locaux et les contraintes variables

Pourquoi c'est mieux :

- les consignes longues restent versionnées dans Git
- le prompt URL reste court et robuste
- on peut améliorer l'agent sans changer le générateur d'URL
- on peut auditer les règles de sélection
- on évite les problèmes d'encodage d'URL
- le même agent peut être utilisé depuis ChatGPT, CLI ou un futur orchestrateur

## Questions ouvertes

1. Format d'export prioritaire : FCPXML, EDL, OTIO ou DaVinci Resolve scripting ?
2. Durée cible des shorts : 12-30s, 20-45s, ou 30-60s ?
3. Style de shorts : humour, storytelling, pédagogie, vlog, punchlines, famille, voyage ?
4. Est-ce qu'on veut générer un seul meilleur cut, ou plusieurs candidats par vidéo ?
5. Faut-il créer des sous-titres brûlés plus tard, ou seulement préparer la timeline ?
6. Doit-on relancer ChatGPT pour chaque vidéo, ou permettre un batch de 5-10 vidéos ?

## Décision proposée

Phase 1 :

- ajouter index SQLite FTS5
- ajouter `--search`
- ajouter `--index`
- créer `docs/SHORTS_AGENT.md`
- ajouter `--open-short-prompt <source_id>`
- générer `viral_candidates.json` et `viral_candidates.md`

Phase 2 :

- générer FCPXML simple
- ajouter `--export-fcpxml <candidate_json>`
- ouvrir automatiquement le dossier de sortie

Phase 3 :

- intégration DaVinci Resolve ou Final Cut plus avancée
- génération de sous-titres
- crop vertical 9:16
- scoring automatique multi-vidéos

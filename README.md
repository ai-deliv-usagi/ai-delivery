# ai-delivery

## GCP deployment

The cloud side is intended to run on Cloud Run:

- `ai-delivery-app`: Flask dashboard, Gemini commentary, local event API, frame API
- `ai-delivery-voicevox`: VOICEVOX Engine
- Cloud Storage bucket: generated audio files
- Vertex AI Gemini via the Cloud Run service account

Terraform lives in `infra/terraform`.

```powershell
.\scripts\deploy-gcp.ps1 `
  -ProjectId "gen-lang-client-0496284195" `
  -Region "asia-northeast1"
```

The deploy script applies Terraform first, then deploys the app to Cloud Run
from local source using Cloud Build. Gemini uses Vertex AI authentication through
the Cloud Run service account, so no Gemini API key or Secret Manager value is
needed.

## Streaming flow

The Cloud Run app is request-driven. It does not start the stream loop when the
container boots. During an active session, it runs a lightweight background
event loop so gift queues, jack expiry, and dashboard timers can advance without
waiting for `/api/frames` or `/api/status`.

Session state is persisted to Cloud Storage under `state/stream-session.json`.
If the Cloud Run app instance is restarted during a stream, the next request can
restore the active session flag, current jack mode, jack expiry, queued gifts,
and pending viewer context.

Create a local virtual environment for `local_agent`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-local.txt
```

```powershell
$env:CLOUD_APP_URL = "https://your-ai-delivery-app-url"
$env:TIKTOK_UNIQUE_ID = "@your_tiktok_id"
python -m local_agent.main
```

`local_agent` starts a session, sends captured Minecraft frames to
`/api/frames`, sends TikTok Live comments/gifts/follows to `/api/events`, plays
returned VOICEVOX audio locally, and stops the session when the process exits.

Useful checks:

```powershell
curl -X POST "$env:CLOUD_APP_URL/api/session/start"
curl "$env:CLOUD_APP_URL/api/status"
curl -X POST "$env:CLOUD_APP_URL/api/session/stop"
```

VOICEVOX runs as a separate Cloud Run service. The app service calls
`VOICEVOX_URL/audio_query` and `VOICEVOX_URL/synthesis`, returns the generated
WAV bytes as base64 in the `/api/frames` response, and the local agent plays the
audio on the local PC.


## Gift-driven character changes

Gifts can temporarily jack the commentator as a different VOICEVOX character,
not just a different outfit or image. Gift mappings live in
`cloud_app/personalities/library.py` as `GIFT_TO_MODE`; each target character
defines its prompt, action style, voice speed/pitch, `speaker_id`, and
`character_image`. The normal mode uses `VOICEVOX_SPEAKER_ID` from the
environment.

For TikTok Live Studio, add a browser source that points to:

```text
https://your-ai-delivery-app-url/character-overlay
```

The overlay polls `/api/status` and swaps to the active character's
`character_image`. Put matching PNG files such as `zundamon.png`, `metan.png`,
and `tsumugi.png` under `static/characters/` or change the image paths in the
personality library to your hosted assets. When a gift activates a full
character change, the app resets the current generation/playback before applying
the new prompt, VOICEVOX speaker, and image.

Character prompts are written for both Minecraft and Pokémon battle streams.
When action selection is useful, the active character's `action_style` tells the
AI how to suggest the next move as a strategy adviser while still prioritizing
TikTok Live viewer interaction. Final game input stays with the streamer.

### Pokémon battle stream guardrails

For Pokémon Champions or Pokémon Showdown, this project treats the AI as a
strategy adviser, not an auto-player. The AI should read the visible battle
state, comments, and active gift-jack character, then suggest a move or plan for
the streamer to execute manually. Do not wire it to controller input, packet
inspection, memory reading, or any other automation that would play the game on
behalf of the streamer.

The intended TikTok Live format is an open-screen strategy meeting: viewers can
see the streamer side, so friend battles may reveal moves, held information, or
reserve Pokémon. That is acceptable as a casual entertainment format if both
sides understand it, but for fairer viewer-participation matches prefer one of
these formats:

- viewers challenge the streamer knowing the stream is open-hand;
- the opponent also streams or voluntarily shares their side for a symmetric
  open-information battle;
- use Casual Battles or Private Battles rather than Ranked Battles or official
  tournament play;
- let gifts temporarily change the adviser character and decision style, while
  the streamer keeps final control.

For Pokémon Champions, Casual Battles are the preferred public-match format for
this adviser-only stream because they are separated from rank progression. Keep
the stream framing clear: the AI is commentary and strategy advice, not gameplay
automation, and the streamer makes every final input manually. Private Battles
are still better when you want the opponent to explicitly opt in to the
open-screen format.

Pokémon Champions is not listed here as a prohibited streaming target. If a
platform, event, or tournament publishes stricter rules, follow those rules and
keep the AI in adviser-only mode.

### Pokémon adviser input contract

A fixed-interval screen capture alone is not enough for reliable Pokémon
advice. Treat the camera frame as visual context, then enrich it with structured
battle state before asking the AI for a suggestion. The minimum useful payload
for each decision point is:

- battle phase: team preview, move selection, switch selection, forced switch,
  post-turn summary, or result screen;
- own active Pokémon: species, form if relevant, current HP percent/status,
  type if known, boosts/drops, held item if known, ability if known, and volatile
  conditions such as substitute/protect/confusion;
- own bench: species, revealed HP/status, fainted state, and whether each member
  is currently switchable;
- selectable actions: the exact move names currently available, remaining PP if
  visible, disabled/locked/recharge constraints, Tera or other battle-system
  availability, and legal switch targets;
- opponent visible state: active Pokémon, HP percent/status, revealed item,
  revealed ability, boosts/drops, known moves, and visible field effects;
- field state: weather, terrain, screens, hazards on each side, tailwind/trick
  room, turn count if tracked, and any other visible timers;
- previous turn memory: the last one to three turns of moves, switches, damage,
  reveals, KOs, and notable prediction misses;
- viewer context: recent comments, poll/gift pressure, and the currently active
  adviser character.

For a live stream, trigger advice on decision boundaries rather than on a blind
fixed interval. A practical flow is: capture continuously for commentary, detect
or manually mark when the move/switch menu is open, build the structured state,
then ask the AI for one recommendation plus a short reason. If OCR is unreliable,
use `/pokemon-control` as a small manual correction panel for the active Pokémon,
HP, status, available moves, field state, and turn history. The panel saves text
to `POST /api/pokemon/state`, and the stream manager appends that text to the
AI context as "ポケモン参謀UI入力". The AI should explicitly say when the state is
uncertain instead of pretending the screen capture contains hidden information.

OCR should be treated as an assistive input, not the source of truth. It can work
for stable labels such as move names, HP percentages, statuses, and menu phase
when the capture region and language are fixed, but it will struggle with fast
animations, overlays, small text, partial occlusion, and unknown opponent sets.
Use OCR to prefill the control panel where possible, then let the streamer keep a
small set of corrections current: legal moves/switches, field timers, revealed
opponent moves/items/abilities, and the last turn summary. The adviser should
prefer the manually saved UI state over raw OCR when they disagree.

## GCP troubleshooting

### Terraform fails with `invalid_grant`

`gcloud auth login` and Terraform's Application Default Credentials are separate.
If Terraform shows an OAuth error such as:

```text
oauth2: "invalid_grant" "Token has been expired or revoked."
```

refresh ADC:

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project gen-lang-client-0496284195
gcloud auth application-default print-access-token
```

Then retry:

```powershell
.\.tools\terraform\terraform.exe -chdir=infra\terraform plan
.\scripts\deploy-gcp.ps1 -ProjectId "gen-lang-client-0496284195"
```

### API enablement errors

The deploy script enables required APIs before Terraform runs:

```text
artifactregistry.googleapis.com
aiplatform.googleapis.com
cloudbuild.googleapis.com
run.googleapis.com
storage.googleapis.com
```

If `PERMISSION_DENIED` appears while enabling an API, the active account likely
needs Service Usage permissions. Enable the API manually in the console or grant
the account a role such as `Service Usage Admin`.

`TIKTOK_UNIQUE_ID` is not stored in Secret Manager and is not deployed to Cloud
Run. Set it in the local environment or local `.env` before running
`python -m local_agent.main`.

### PowerShell and Terraform `-chdir`

Pass Terraform arguments carefully in PowerShell. The deploy script resolves the
Terraform directory and passes `-chdir` as an expanded argument. If you run
Terraform manually, this form is safe:

```powershell
.\.tools\terraform\terraform.exe -chdir=infra\terraform plan
```

An error like this means the path was passed literally instead of expanded:

```text
Error handling -chdir option: chdir $terraformDir: The system cannot find the file specified.
```

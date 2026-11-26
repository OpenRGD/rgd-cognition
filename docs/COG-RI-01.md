# COG–RI–01 — Read-only ObservationRef adapter e handoff verso Reality Ingress

**25 novembre 2026 · candidato, non normativo, non attuante · Review/CI senza deploy.**

## Fonti e ownership verificati

- RI [`main`](https://github.com/OpenRGD/rgd-reality-ingress) alla baseline v0.4, codice storico sperimentale. Il **contratto per i consumer non è su `main`**, ma in [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4), head `5372f758df79c93fc887f3858d878635447f4a4d`, blob Git dello schema `3d92e074e71593bf6db0a735394c628ea131668d`.
- Handoff specifico: [`RI-TO-COGNITION.md`](https://github.com/OpenRGD/rgd-reality-ingress/blob/feat/ri-integration-01-pipeline-contract/docs/handoffs/RI-TO-COGNITION.md); handoff dell'ecosistema: [`docs/handoffs/README.md`](https://github.com/OpenRGD/rgd-reality-ingress/blob/feat/ri-integration-01-pipeline-contract/docs/handoffs/README.md).
- COG di base [PR #7](https://github.com/OpenRGD/rgd-cognition/pull/7) al commit `3b78e835ca963ea80ee20885d3552e5f200c2b99`; mantiene C1 IMU e l'unica ammissione Core-B nel percorso opt-in, le proiezioni Core-D senza History writer e il Core classico pinned `afe1a831...`.
- Nessuna prova di deploy dell'adapter RI sul robot. Non confondere test GitHub, API candidate e publisher/transport funzionanti sul mini-PC.

**Owner:** camera/acquisizione -> un solo host publisher; IMU -> publisher host/Console, Voice -> owner microfono/VAD/STT, Perception -> interpretazione derivata, RI -> evidence refs/provenienza locale, COG -> Attention/Work/Reasoning; Chronograf/History -> tempo qualificato/scrittura, Visual Feedback/Voice -> output. RI/COG non aprono periferiche né emettono SELF/goal/voice/motion.

## Decisione: adapter minimo realmente sensato

Il riferimento `ri.consumer-observation-ref.v0.1-candidate` contiene **metadati e identificatori**, non letture IMU numeriche, frame/video autorizzati, testo ASR o risultato Perception. Non è corretto convertirlo automaticamente in un `ConsoleImuRecord`, un `AttentionCue` C1 o un `InputEvent` COG-01: `InputEvent.origin` non rappresenta fedelmente `unknown` di RI. Questo non è un difetto da riparare inventando un'origine `PHYSICAL` o `SIMULATED`.

Si aggiunge solo `src/rgd_cognition/ri_observation_ref.py`, opt-in e **reference-only**, e un notice locale chiuso `cog_ri_reference_notice_v0.1-candidate` in `schemas/ri-reference-notice.schema.json`. Il consumer verifica i byte dello schema RI candidato contro il **Git blob pinned**, rifiuta record con campi inattesi o false attestazioni e preserva esattamente `observation_id`, `payload_sha256_hex`, `source_id`, modality, frame, sequence e il timestamp di ricezione originale.

Il trusted host fornisce **fuori dal payload** un canale di lettura locale opaco, ACL/consenso, policy di sorgente e un rapporto di disponibilità delle evidenze. Nessuno di questi canali attesta l'hardware o rappresenta autenticazione crittografica remota. Default: metadata_access/consent/payload_access disabilitati. Se manca un'autorizzazione, il consumer non espone ID/hash. `REDACTED`/`ERASED`/`NOT_AUTHORIZED` sono blocchi senza notice. Un `UNAVAILABLE` rimane tale e non viene sostituito con valore zero/falso. La verifica opzionale di payload byte è locale e limitata a 1 MiB; l'adapter non crea né contiene un altro EvidenceStore e **non legge automaticamente file o rete**.

La freschezza `FRESH/STALE` qualifica **soltanto la ricezione host** e soltanto se il trusted host dichiara esplicitamente un *same-boot monotonic domain* con boot e clock-domain esattamente corrispondenti. Se boot o corrispondenza mancano, il risultato è `UNKNOWN`; non si confrontano clock di host diversi. `source_measurement_time` e `chronograf_anchor_ref` rimangono null nel ref RI, nessun TimeAtom inventato. Una replay dello stesso record è inerte; una seconda richiesta con stesso `observation_id` e contenuto differente è un conflitto. Il backlog è limitato e non evince idempotency key durante la sessione.

**Invarianti sempre falsi:** `can_generate_goal=false`, `may_actuate=false`, `grants_authority=false`, `life_id=null`, `chronon_id=null`; source authentication `NOT_VERIFIED`, calibration `UNVERIFIED`, epistemic `UNKNOWN`, memory/perception non connessa. `verified_local_hash` non diventa `SOURCE_INTEGRITY_VERIFIED` di COG-02: sono domini di verifica diversi.

## Relazione con C1/Work e con i dati derivati

- **IMU:** il C1 esistente continua a ricevere *campioni numerici normalizzati* esclusivamente dall'adapter autorizzato del publisher Console/IMU. Un RI ref può essere associato in futuro a quelle osservazioni solo tramite una relazione esatta fra campione, digest, sequenza e fonte autenticata; **questo profilo non effettua quel binding**.
- **Perception:** result interpretativi con model/config/calibration/provenance e incertezza avranno un contratto separato; RI non è il classificatore e il ref non identifica una persona/robot come SELF.
- **Voice:** transcript/lifecycle `speaking` sono *derivati o report di stato*, non audio grezzo o output fisicamente ascoltato; il consumer non apre microfoni né invoca TTS.
- **Work:** nessuna seconda ammissione o scheduler. Il notice resta separato dall'agenda, perché la sola presenza del ref non autorizza nuovi goal.
- **Offline:** se RI non è disponibile il percorso COG precedente continua; disabilitare questo consumer non influisce su C1, Somatic o feedback.

## Conformance e rollback

Test con il **produttore reale RI** — `EvidenceStore.record`, `verified_ref_from_store`, `unverified_ref_from_envelope` — su payload *sintetici*, insieme al consumer COG. Copertura: ID/hash/frame/tempo preservati, integrity verificata soltanto localmente, schema/identity/anchor falsificati, payload corrotto/mancante, ACL/consenso, erasure/redaction, multi-host UNKNOWN, stale/future/same-boot, duplicati/conflitti, quote/backpressure, compatibilità generic JSONL, no I/O/goal e COG disponibile senza RI. CI installa entrambi i pacchetti in ambiente di test; **non esegue un hardware pilot**.

Il test fisico facoltativo richiede approvazione esplicita di chi possiede la sorgente: un solo publisher, fan-out di metadati read-only con limite di durata/volumi, nessun nuovo device open, verifica avvio/stop senza effetto sul controllo fisico, rollback disabilitando il consumer. Il pilot non è parte di questa PR.

## Handoff di ritorno RI → owner RI

**Decisione COG:** accettiamo lo schema `ri.consumer-observation-ref.v0.1-candidate` come input opt-in **di sola referenza**, con pin Git esplicito e senza elevazione di fiducia. `verified_local_hash` è integrità locale, non source/robot/Chronograf/Life verification. Metadata ACL, consenso, corrispondenza clock/boot e disponibilità del media sono affidati al trusted producer/host. COG non apre camere, microfoni, seriale IMU o rete; non duplica EvidenceStore, Perception, Voice, GoalAdmission, Work, Chronon, Visual Feedback o Somatic.

**Contratto:** ref RI originale immutato -> notice locale COG con `session_scope=SESSION_SCOPED_UNBOUND`, origine epistemica `UNKNOWN`, freshness qualificata o `UNKNOWN`, evidence disponibile/bloccata, e nessun goal/effetto/identità/commit. Primo test reale di pipeline è del *codice producer/consumer*, con fixture sintetiche, non dell'hardware. La PR COG dedicata resta draft e non promuove RI PR #4.

**Punti aperti RI/owner:** trasporto read-only autenticato e revocabile, status `availability` della risorsa/evidence dopo retention, consenso effettivo di immagine/audio, ID e boot dei publisher realmente installati, conversione fra ricezione publisher e sessione subscriber, legame numerico IMU→RI ref, contratto PerceptionResult e media ACL/rate limit. Il `PayloadRef` di RI non concede di per sé accesso al media. Nessuna schedulazione sensoriale può dipendere dall'I/O del Vault.

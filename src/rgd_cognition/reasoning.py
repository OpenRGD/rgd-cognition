"""Small deterministic baseline. No LLM, model download, plugin loader or tools."""
from __future__ import annotations
from typing import Protocol


class Reasoner(Protocol):
    # In-process providers are TRUSTED CODE, not a sandbox for extensions.
    revision: str

    def assess(self, event: dict, context: dict, memory: dict, event_ref: str) -> dict: ...


class BaselineReasoner:
    revision = "deterministic-baseline-v1"

    def assess(self, event: dict, context: dict, memory: dict, event_ref: str) -> dict:
        text = event["text"].casefold().strip().rstrip("?!.")
        if event["kind"] == "OBSERVATION_NOTICE":
            code, kind = "OBSERVATION_REPORTED", "REPORT"
        elif text in {"chi sei", "who are you"}:
            code, kind = "IDENTITY_UNBOUND", "ABSTAIN"
        elif text in {"cosa ricordi", "what do you remember"}:
            code, kind = "MEMORY_UNAVAILABLE", "ABSTAIN"
        elif text in {"stato", "status", "come stai"}:
            code, kind = "STATUS_REPORT", "REPORT"
        else:
            code, kind = "BASELINE_ABSTAINS", "ABSTAIN"
        return {"kind": kind, "response_code": code, "evidence_refs": [event_ref]}


RESPONSES = {
    "IDENTITY_UNBOUND": "Non ho ancora un binding verificato tra profilo RGD, istanza fisica e identità Life.",
    "STATUS_REPORT": "Il ciclo cognitivo di laboratorio è attivo. Identità non verificata, memoria Chronon non collegata e nessuna interfaccia motoria.",
    "MEMORY_UNAVAILABLE": "La memoria storica Chronon non è collegata. Non posso dichiarare ricordi persistenti.",
    "BASELINE_ABSTAINS": "Questa richiesta supera il ragionatore deterministico iniziale. Nessun modello linguistico è collegato.",
    "PROVIDER_UNAVAILABLE": "Il ragionatore non ha restituito un risultato utilizzabile. Mi astengo.",
    "PROVIDER_INVALID": "La proposta non rispetta i contratti o i riferimenti disponibili. Mi astengo.",
    "PROVIDER_BUDGET_EXCEEDED": "Il ragionatore ha superato il budget previsto. Il risultato non viene utilizzato.",
}


def render(code: str, event: dict) -> str:
    if code == "OBSERVATION_REPORTED":
        return (
            "Ho ricevuto una notifica: origine " + event["origin"]
            + ", stato epistemico " + event["epistemic_status"]
            + ", calibrazione " + event["calibration_status"]
            + ". Queste etichette sono dichiarate dalla sorgente, non verificate; non certificano una posa o un evento fisico."
        )
    return RESPONSES[code]

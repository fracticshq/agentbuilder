# Lal Kitab connector contract (v1)

Lal Kitab responses are optional, untrusted connector input. The runtime never
states a prediction/remedy as calculated unless it receives a valid chart
context. If the chart endpoint is unavailable or malformed, it returns the
standard abstention message instead of inventing an interpretation.

## Request (`lalkitab.request.v1`)

```json
{
  "birth_date": "YYYY-MM-DD",
  "birth_time": "HH:MM",
  "birth_place": "display name",
  "timezone": "+05:30",
  "latitude": 28.6139,
  "longitude": 77.2090,
  "question": "optional user question"
}
```

`birth_date`, `birth_time`, and a resolved place/timezone are required before a
chart request. Geocoding ambiguity produces a clarification rather than a
best-guess location. Raw birth details are treated as sensitive: they are not
put in public activity/diagnostic metadata and follow the privacy retention
contract.

## Response (`lalkitab.chart.v1`)

The connector may return any provider-native chart envelope, but the runtime
projects only verified facts into:

```json
{
  "chart_context": {"provider-specific": "validated internally"},
  "summary": {
    "style": "north_indian",
    "ascendant": {"sign_number": 1, "name": "Aries", "hindi": "Mesh"},
    "houses": [{"house": 1, "sign_number": 1, "rashi": "Aries", "planets": ["Su"]}]
  }
}
```

`summary` is derived deterministically by `kundali_chart.py`; missing facts
remain absent. The schema is versioned at the connector boundary. Additive
provider fields are ignored; a breaking input/output change requires a new
`lalkitab.*.vN` label and fixtures in the Lal Kitab evaluation corpus.

## Error and abstention semantics

- Invalid/incomplete profile: request only the missing field(s).
- Ambiguous location: ask the user to choose a candidate.
- Provider/chart failure: return `LAL_KITAB_CHART_UNAVAILABLE_MESSAGE` and no
  prediction/remedy claim.
- Unsupported domain or prompt injection: normal agent safety policies apply.

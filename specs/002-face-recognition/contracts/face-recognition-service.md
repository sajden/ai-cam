# Contract: face-recognition Service API

**Service**: `face-recognition` (new Docker container)
**Base URL**: `http://face-recognition:8082` (internal `ai_net`)
**Auth**: `X-API-Key` header (shared secret via `FACE_RECOGNITION_API_KEY` env var)

---

## POST /recognize

Identify a person from a JPEG image.

**Request**:
```
Content-Type: multipart/form-data
Field: image (JPEG bytes)
Field: min_score (float, optional, default 0.55)
```

**Response 200**:
```json
{
  "matched": true,
  "name": "Sebastian",
  "confidence": 0.72,
  "bbox": [120, 45, 380, 310],
  "face_detected": true
}
```

**Response 200 (unknown)**:
```json
{
  "matched": false,
  "name": null,
  "confidence": 0.31,
  "bbox": [120, 45, 380, 310],
  "face_detected": true
}
```

**Response 200 (no face)**:
```json
{
  "matched": false,
  "name": null,
  "confidence": 0.0,
  "bbox": null,
  "face_detected": false
}
```

---

## POST /enroll

Add or update a face for a named person.

**Request**:
```
Content-Type: multipart/form-data
Field: name (string) — person's first name
Field: image (JPEG bytes) — clear face photo
```

**Response 200**:
```json
{
  "ok": true,
  "name": "Sebastian",
  "embedding_count": 3
}
```

**Response 400**:
```json
{
  "ok": false,
  "reason": "no_face_detected"
}
```

---

## DELETE /persons/{name}

Remove all stored embeddings for a person.

**Response 200**:
```json
{ "ok": true, "name": "Sebastian", "removed_count": 3 }
```

---

## GET /health

**Response 200**:
```json
{
  "ok": true,
  "gpu": true,
  "provider": "CUDAExecutionProvider",
  "enrolled_persons": 2,
  "model": "buffalo_l"
}
```

# KEYROTOR

**Router de rotación de claves LLM multi-proveedor, con cero secretos.**

Inspirado en el gateway de LiteLLM y en las mejores prácticas de integración
de APIs de IA de 2026, `keyrotor` enruta peticiones de chat hacia varios
proveedores de modelos (OpenRouter, NVIDIA NIM, Google AI Studio, OpenCode Zen),
rotando claves automáticamente, con failover, caché TTL y cortacircuitos.

Las claves se cargan **exclusivamente desde variables de entorno**, nunca se
escriben en disco ni se envían al navegador: el dashboard solo ve claves
enmascaradas (`sk-a...1234`).

## Las 3 reglas del proyecto

1. **NO SECRETS** — ninguna clave real entra en git, logs, métricas ni UI.
   Todo texto que sale del router pasa por el redactor antes de imprimirse.
2. **Backend proxy** — el frontend habla solo con `keyrotor`; jamás ve una
   clave ni hace llamadas directas a los proveedores.
3. **Rotación sin downtime** — cada proveedor tiene un pool de claves
   primarias + fallback. Una clave muerta (401/403) se descarta y se usa la
   siguiente sin interrumpir el servicio.

## Arquitectura

```
                       +-----------------------------+
  navegador            |  keyrotor  (HTTP stdlib)     |
  dashboard  --------> |  GET  /  (index.html)        |
  (sin secretos)       |  GET  /api/status            |
                       |  POST /v1/chat/completions   |
                       +-------------+---------------+
                                     |
                                     v
                          +--------------------+
                          |  RotatingRouter    |
                          |  - rotación claves |
                          |  - failover        |
                          |  - retries/backoff |
                          |  - cortacircuito   |
                          |  - caché TTL       |
                          +---------+----------+
                                    |
                    +---------------+----------------+
                    |               |                |
                    v               v                v
              +-----------+  +-----------+   +-------------+
              | OpenRouter|  |  NVIDIA   |   | Google/AI   |
              | (bearer)  |  | (bearer)  |   | (query key) |
              +-----------+  +-----------+   +-------------+
                          claves: variables de entorno
```

## Quickstart

```bash
# 1. instalar (modo editable)
pip install -e .

# 2. configurar claves (nunca commitear .env)
copy .env.example .env      # Windows
# cp .env.example .env      # Linux/macOS
# rellena .env con tus claves reales

# 3. arrancar servidor + dashboard
python -m keyrotor serve --host 127.0.0.1 --port 8000
# abrir http://127.0.0.1:8000/

# 4. chat por CLI
python -m keyrotor chat "hola"
python -m keyrotor chat "explícame qué es un router" --model gpt-4o-mini
python -m keyrotor chat "prioridad nvidia" --provider-order nvidia,openrouter

# 5. estado
python -m keyrotor status
```

## Variables de entorno

| Variable | Descripción |
|---|---|
| `GOOGLE_API_KEYS` | claves de Google AI Studio, separadas por comas |
| `NVIDIA_API_KEYS` | claves NVIDIA NIM, separadas por comas |
| `OPENROUTER_API_KEYS` | claves OpenRouter, separadas por comas |
| `OPENCODE_API_KEYS` | claves OpenCode Zen, separadas por comas |
| `KEYROTOR_PROVIDER_ORDER` | orden de failover, ej. `openrouter,nvidia,google` |
| `KEYROTOR_CACHE_TTL` | TTL global de caché (segundos) |
| `KEYROTOR_MAX_RETRIES` | reintentos por petición |
| `KEYROTOR_BACKOFF` | factor de backoff exponencial |
| `KEYROTOR_BREAKER_THRESHOLD` | fallos consecutivos para abrir el circuito |
| `KEYROTOR_BREAKER_COOLDOWN` | segundos antes de la sonda half-open |
| `KEYROTOR_PORT` | puerto por defecto del servidor |

## API HTTP

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | dashboard |
| `GET` | `/health` | `{"ok": true, "version": "1.0.0"}` |
| `GET` | `/api/status` | métricas del router (claves enmascaradas) |
| `GET` | `/api/events` | últimos eventos (redactados) |
| `POST` | `/v1/chat/completions` | API compatible con OpenAI |

Ejemplo:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hola"}]}'
```

Respuesta:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gpt-4o-mini",
  "provider": "opencode",
  "cache_hit": false,
  "choices": [{"message": {"role": "assistant", "content": "..."}}]
}
```

En caso de fallo total devuelve `502` con `{"error": {...}}` (texto redactado).

## Proveedores integrados

| Nombre | Base URL | Auth | Modelo por defecto |
|---|---|---|---|
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions` | bearer | `meta-llama/llama-3.3-70b-instruct:free` |
| `nvidia` | `https://integrate.api.nvidia.com/v1/chat/completions` | bearer | `meta/llama-3.1-8b-instruct` |
| `google` | `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` | query `key` | `gemini-3.6-flash` |
| `opencode` | `https://api.opencode.ai/v1/chat/completions` | bearer | `gpt-4o-mini` |

## Semántica de enrutamiento

- **Rotación por clave**: un `401`/`403` marca la clave como muerta, se
  descarta del pool y se reintenta con la siguiente clave del mismo
  proveedor (intentos ilimitados hasta agotar el pool).
- **Failover entre proveedores**: proveedor sin claves, con circuito abierto
  o con error 4xx → se pasa al siguiente del `provider_order`.
- **Retries**: `429`/`408`/`5xx` se reintentan con backoff exponencial
  + jitter, **sin descartar la clave**. Errores de red tampoco descartan.
- **Cortacircuito**: 5 fallos consecutivos abren el circuito 60 s; pasado
  el cooldown se envía una sonda half-open: éxito cierra, fallo reabre.
- **Caché**: hash exacto `SHA-256(proveedor + URL + body)` con TTL por
  proveedor (por defecto 300 s). Una repetición idéntica cuesta 0 tokens.

## Seguridad

- Las claves solo existen en memoria, leídas de variables de entorno.
- `keyrotor.redact` enmascara (`sk-a****34`) y detecta patrones de claves
  (OpenAI, OpenRouter, NVIDIA, Google, JWT, GitHub PAT, HF, AWS...).
- Todo evento, log y error se filtra por el redactor antes de salir.
- El frontend añade su propia capa de enmascarado por defensa en profundidad.
- `scripts/secret_scan.py` recorre el repo buscando patrones de secretos;
  el CI lo ejecuta en cada push.

## Tests

```bash
python -m pytest tests -q
python scripts/secret_scan.py
```

Los tests del router usan un transport falso (sin red) y claves de juguete
(`sk-fake-...`); ninguno toca la red ni usa claves reales.

## Datos abiertos

El directorio [`open-data/`](open-data/) trae un pack abierto del catalogo de
modelos LLM (id, contexto, precio por millon de tokens, modalidad), obtenido
del endpoint publico de OpenRouter **sin clave de API**.

```bash
python scripts/fetch_open_data.py   # regenera open-data/llm-models.{json,csv}
```

Ver [`open-data/README.md`](open-data/README.md) para fuente y licencia.

## Proyectos open similares

- [LiteLLM](https://github.com/BerriAI/litellm) — proxy/gateway multi-proveedor con rotacion y presupuestos.
- [Portkey AI Gateway](https://github.com/Portkey-AI/gateway) — gateway con failover, cache y guardrails.
- [Bifrost](https://github.com/maximhq/bifrost) — gateway LLM de alto rendimiento en Go.
- [Helicone](https://github.com/Helicone/helicone) — observabilidad y caching para LLM.
- [RouteLLM](https://github.com/lm-sys/RouteLLM) — enrutado inteligente coste/calidad.
- [GPTRouter](https://github.com/Writesonic/GPTRouter) — router con fallback entre proveedores.

## Licencia

MIT — Copyright (c) 2026 Pedro Belentani. Ver [LICENSE](LICENSE).

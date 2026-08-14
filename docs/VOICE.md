# OpenPower Input and Voice

All inputs produce one `IntentInput`, then follow the normal APX pipeline:

`input -> transcript/parse -> intent -> capability -> policy -> prepare -> confirmation -> execute -> verify -> receipt`

Text and voice share the same router. A held configured key means Action mode;
a short tap means conversation mode. Desktop-global key event adapters remain
optional platform components because Linux and macOS have different permission
models.

`whisper.cpp` is optional and replaceable. No model downloads occur during
installation. OpenWakeWord is not bundled; future hands-free mode is explicit
opt-in. Continuous listening is never the default.

High-risk speech produces `prepare_required`; it does not execute from a spoken
sentence. Raw audio is ephemeral by default and never enters analytics.

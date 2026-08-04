# Ollama model profiles

Frozen interface profiles live under
`benchmarks/ollama-prompts/profiles/`. They contain interface and generation
behavior only; they do not contain product-family corrections or hidden CAD
facts.

| Profile | Exact model | Full digest | Template family | Hash |
| --- | --- | --- | --- | --- |
| `cad-coder-q8.yaml` | `volundr-cad-coder-native:q8_0` | `78a44226975041264edeee70beb170e2a02f32949f3ea8de51b3fcdc5b73ae51` | Qwen2 ChatML | `d9d01e89cccf4fbece5e0850d1948a7df02f77805ee0c2a6c31117af33156cf5` (iteration 2) |
| `procad-coder-q8.yaml` | `volundr-procad-coder-native:q8_0` | `92d3a018374f3603e6c2a4cc72a8a987c525b0398bea29b7382a19e9ff0a3120` | Qwen2 ChatML | `6edd575bbd0c72336e2f2dc2d17aa0064874004c67d642ba70513cc685569a5b` (iteration 1) |
| `qwen25-cadquery-q4.yaml` | `hf.co/yuvit-batra/qwen2.5-coder-7b-cadquery-gguf:Q4_K_M` | `692bb3cfa2f456c1170a85bfbc28f98be5f5a2df00ccf1be2365304920a06256` | Qwen2 ChatML/FIM | `6009db8978d94402f2b097832374d08783b658e6ed0c333674b383867ace74e3` (iteration 1) |
| `qwen25-coder-14b-q5.yaml` | `qwen2.5-coder:14b-instruct-q5_K_M` | `05d16c5ac1c126618f66f52d6099514df79bf104fcb889bee9069a751822d3e7` | Qwen2 ChatML/FIM | `e9a63b02095a1db92ec8ee61db5c4af70033a6a8f1111aab65ccb9c1f4943dd0` (iteration 3) |
| `deepseek-coder-v2-lite-q4.yaml` | `deepseek-coder-v2:16b-lite-instruct-q4_K_M` | `dac6ff6589c90902a8e5b11583492d17e87b6f3ddb25e558c593110a23a547aa` | DeepSeek User/Assistant | `e73b6cc45b570e031bfb3bd626e6eae781dd8f5946000a174694876716e5d750` (iteration 1) |
| `c3dv0.yaml` | `joshuaokolo/C3Dv0:latest` | `0e44735f72fb7dbb6e28af836e6b365bc44c32007e7b8cb1d8ae31c7a0b574fa` | Gemma 3n turns | `274b13bbf4535e2505a2deb07c2d1edc66822160dd99996e2a3068abf900c1a7` (iteration 1) |

The complete templates, stop parameters, capabilities, and `/api/tags` plus
`/api/show` payloads remain in the untracked calibration evidence.

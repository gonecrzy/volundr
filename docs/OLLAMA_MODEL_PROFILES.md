# Ollama model profiles

Frozen interface profiles live under
`benchmarks/ollama-prompts/profiles/`. They contain interface and generation
behavior only; they do not contain product-family corrections or hidden CAD
facts.

| Profile | Exact model | Full digest | Template family | Hash |
| --- | --- | --- | --- | --- |
| `cad-coder-q8.yaml` | `volundr-cad-coder-native:q8_0` | `78a44226975041264edeee70beb170e2a02f32949f3ea8de51b3fcdc5b73ae51` | Qwen2 ChatML | `5f27d3ceb799177bf5a68d326646e4f8e1f63311dcaba9c8476998586a223336` |
| `procad-coder-q8.yaml` | `volundr-procad-coder-native:q8_0` | `92d3a018374f3603e6c2a4cc72a8a987c525b0398bea29b7382a19e9ff0a3120` | Qwen2 ChatML | `abb398f5dc53e33ee7836317738d1b1ff83db4829b294f6d547116f2ddabef3f` |
| `qwen25-cadquery-q4.yaml` | `hf.co/yuvit-batra/qwen2.5-coder-7b-cadquery-gguf:Q4_K_M` | `692bb3cfa2f456c1170a85bfbc28f98be5f5a2df00ccf1be2365304920a06256` | Qwen2 ChatML/FIM | `1ec2429a3364cdcb5cabb6b085bd3ba5bc2b95cd25c87c0d30bccf71974e7a75` |
| `qwen25-coder-14b-q5.yaml` | `qwen2.5-coder:14b-instruct-q5_K_M` | `05d16c5ac1c126618f66f52d6099514df79bf104fcb889bee9069a751822d3e7` | Qwen2 ChatML/FIM | `77d7398b0531a109d5e5d0b47100b2f6cff24fe981e24ea3dc91d5c515bd96e8` |
| `deepseek-coder-v2-lite-q4.yaml` | `deepseek-coder-v2:16b-lite-instruct-q4_K_M` | `dac6ff6589c90902a8e5b11583492d17e87b6f3ddb25e558c593110a23a547aa` | DeepSeek User/Assistant | `7baa561a929cec407bfc4a31b4e853647a3332f28f9e57454e41d4b6759e1d31` |
| `c3dv0.yaml` | `joshuaokolo/C3Dv0:latest` | `0e44735f72fb7dbb6e28af836e6b365bc44c32007e7b8cb1d8ae31c7a0b574fa` | Gemma 3n turns | `c598b4ee42811fb85d613deddf88d42f34d9c321d9d9dcf4099bc7c98f4ac848` |

The complete templates, stop parameters, capabilities, and `/api/tags` plus
`/api/show` payloads remain in the untracked calibration evidence.

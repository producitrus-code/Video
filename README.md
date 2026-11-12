# Video — legendas animadas

Pipeline: Whisper (transcrição por palavra) → `render.py` (Pillow, overlay RGBA por frame) → ffmpeg (H.264).

- `projects/*.json` — um arquivo por vídeo: cards, palavras-chave, correções, paleta, posição da legenda
- `source/**/transcript.json` — timestamps por palavra (Whisper: `python3 work/transcribe.py <video> <saida.json>`)
- `fonts/` — Inter Tight (Black) + Instrument Serif Italic (OFL)

```bash
python3 render.py --config projects/docinhos.json --preview 4.6 22
python3 render.py --config projects/docinhos.json
```

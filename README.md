# Video — legendas animadas

Pipeline: Whisper (transcrição por palavra) → `render.py` (Pillow, overlay RGBA por frame) → ffmpeg (H.264).

- `edit.json` — cards dos tópicos, palavras-chave em destaque, correções de transcrição, paleta
- `source/transcript.json` — timestamps por palavra
- `fonts/` — Inter Tight (Black) + Instrument Serif Italic (OFL)

```bash
python3 render.py --preview 4.6 22   # stills em output/preview
python3 render.py                    # vídeo final em output/EDITADO_NC.mp4
```

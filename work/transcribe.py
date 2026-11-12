import json, subprocess, sys
import numpy as np
from faster_whisper import WhisperModel
src, dst = sys.argv[1], sys.argv[2]
pcm = subprocess.run(["ffmpeg","-v","error","-i",src,"-f","f32le","-ac","1","-ar","16000","-"],capture_output=True,check=True).stdout
m = WhisperModel("large-v3", device="cpu", compute_type="int8")
segs, _ = m.transcribe(np.frombuffer(pcm,dtype="float32"), language="pt", word_timestamps=True, vad_filter=True, beam_size=5)
out=[]
for s in segs:
    out.append({"start":s.start,"end":s.end,"text":s.text,"words":[{"w":w.word,"s":w.start,"e":w.end} for w in s.words]})
    print(f"[{s.start:6.2f}-{s.end:6.2f}] {s.text}", flush=True)
json.dump(out, open(dst,"w"), ensure_ascii=False, indent=1)

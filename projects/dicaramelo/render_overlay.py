"""Uso: render.py <edl.json> <video_cru> <saida.mp4> [--only 3,7]
Renderiza cada corte (1920x1080@30, recorte 16:9 em y, slow-mo, Ken Burns em fotos),
concatena, sobrepõe na janela [start,end] do vídeo cru com áudio original,
e gera check.jpg (1º/meio/último frame de cada corte + bordas da janela)."""
import sys, os, json, subprocess
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont
args = sys.argv[1:]; only = None
if "--only" in args:
    i = args.index("--only"); only = {int(x) for x in args[i+1].split(",")}; del args[i:i+2]
edl_p, raw, out = args
E = json.load(open(edl_p)); START, END, CUTS = E["start"], E["end"], E["cuts"]
FPS, W, H = 30, 1920, 1080
odir = os.path.dirname(os.path.abspath(out)); seg = os.path.join(odir, "_seg"); os.makedirs(seg, exist_ok=True)
fr = lambda t: round((t-START)*FPS)
def job(i):
    c = CUTS[i]; t2 = CUTS[i+1]["t"] if i+1 < len(CUTS) else END
    n = fr(t2) - fr(c["t"]); f = c["file"]; y = c.get("y",0.5); o = f"{seg}/{i:03d}.mp4"
    if os.path.splitext(f)[1].lower() in (".jpg",".jpeg",".png"):
        vf = (f"scale={2*W}:{2*H}:force_original_aspect_ratio=increase,crop={2*W}:{2*H}:(iw-{2*W})/2:(ih-{2*H})*{y},"
              f"zoompan=z='1+0.07*in/{n}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={W}x{H}:fps={FPS},scale=out_color_matrix=bt709:out_range=tv,format=yuv420p")
        cmd = ["ffmpeg","-v","error","-y","-loop","1","-framerate",str(FPS),"-i",f,"-vf",vf]
    else:
        sp = c.get("speed",1); pre = f"setpts={sp}*PTS," if sp != 1 else ""
        trc = subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=color_transfer","-of","csv=p=0",f],capture_output=True,text=True).stdout.strip()
        if trc in ("arib-std-b67","smpte2084"):
            pre += "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"

        vf = (f"{pre}fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={W}:{H}:(iw-{W})/2:(ih-{H})*{y},setsar=1,format=yuv420p")
        cmd = ["ffmpeg","-v","error","-y","-ss",str(c.get("src",0)),"-i",f,"-an","-vf",vf]
    cmd += ["-frames:v",str(n),"-c:v","libx264","-preset","medium","-crf","14","-r",str(FPS),"-colorspace","bt709","-color_primaries","bt709","-color_trc","bt709","-color_range","tv",o]
    r = subprocess.run(cmd, capture_output=True, text=True)
    got = subprocess.run(["ffprobe","-v","error","-count_frames","-select_streams","v","-show_entries","stream=nb_read_frames","-of","csv=p=0",o],capture_output=True,text=True).stdout.strip()
    return i, n, got, r.stderr.strip()[:200]
idx = [i for i in range(len(CUTS)) if only is None or i in only]
with ThreadPoolExecutor(3) as ex:
    for i, n, got, err in ex.map(job, idx):
        flag = "" if str(n) == got else "  <-- FRAMES ERRADOS (src+dur passa do fim do clipe?)"
        print(f"{i:02d} {os.path.basename(CUTS[i]['file'])} frames {got}/{n}{flag} {err}")
with open(f"{seg}/list.txt","w") as L:
    for i in range(len(CUTS)): L.write(f"file '{i:03d}.mp4'\n")
track = f"{seg}/track.mp4"
subprocess.run(["ffmpeg","-v","error","-y","-f","concat","-safe","0","-i",f"{seg}/list.txt","-c","copy",track],check=True)
fc = (f"[0:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[base];"
      f"[base][1:v]overlay=eof_action=pass:enable='between(t,{START},{END})'[v]")
subprocess.run(["ffmpeg","-v","error","-y","-i",raw,"-itsoffset",str(START),"-i",track,"-filter_complex",fc,
                "-map","[v]","-map","0:a?","-c:v","libx264","-preset","slow","-crf","15","-pix_fmt","yuv420p",
                "-colorspace","bt709","-color_primaries","bt709","-color_trc","bt709","-color_range","tv","-c:a","copy","-movflags","+faststart",out],check=True)
# painel de conferência
font = ImageFont.load_default(size=16); w, h = 192, 108
def grab(src, t, p):
    subprocess.run(["ffmpeg","-v","error","-y","-ss",f"{max(t,0):.3f}","-i",src,"-frames:v","1","-vf",f"scale={w}:{h}",p])
    return Image.open(p)
rows = [("borda", [START-0.2, START+0.1, END-0.1, END+0.15])] + [
    (i, [c["t"]+0.05, (c["t"]+(CUTS[i+1]["t"] if i+1<len(CUTS) else END))/2, (CUTS[i+1]["t"] if i+1<len(CUTS) else END)-0.08])
    for i, c in enumerate(CUTS)]
cols = 2; rh = (len(rows)+cols-1)//cols
sh = Image.new("RGB",(cols*(4*w+10), rh*h),"black"); d = ImageDraw.Draw(sh)
for k,(lab,ts) in enumerate(rows):
    x0 = (k%cols)*(4*w+10); y0 = (k//cols)*h
    for j,t in enumerate(ts): sh.paste(grab(out,t,f"{seg}/_c.jpg"),(x0+j*w,y0))
    d.text((x0+3,y0+2), str(lab), fill="yellow", font=font)
sh.save(os.path.join(odir,"check.jpg"), quality=80)
dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out],capture_output=True,text=True).stdout.strip()
print(f"OK {out} ({dur}s, {os.path.getsize(out)/1e6:.0f} MB) | conferência: {odir}/check.jpg")

"""Encode the real CI browser flow, with visible captions and a sidecar VTT."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import textwrap
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.input=a.input.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
rows=json.loads((a.input/'captions.json').read_text())
def stamp(v):
    ms=round(v*1000);s=ms//1000;return f'{s//3600:02}:{s//60%60:02}:{s%60:02}.{ms%1000:03}'
(a.output/'screencast.vtt').write_text('WEBVTT\n\n'+'\n'.join(f"{i+1}\n{stamp(r['start'])} --> {stamp(r['end'])}\n{r['text']}\n" for i,r in enumerate(rows)),encoding='utf-8')
info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(a.input/'studio-tour.webm')]))['streams'][0]
ass=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {info['width']}
PlayResY: {info['height']}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,26,&H00FFFFFF,&H000000FF,&H00000000,&H70000000,0,0,0,0,100,100,0,0,3,8,0,2,48,48,24,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
def ass_time(v):
    ticks=round(v*100);seconds=ticks//100;return f'{seconds//3600}:{seconds//60%60:02}:{seconds%60:02}.{ticks%100:02}'
for row in rows:
    caption=r'\N'.join(textwrap.wrap(row['text'],width=96))
    ass+=f"Dialogue: 0,{ass_time(row['start'])},{ass_time(row['end'])},Default,,0,0,0,,{caption}\n"
subtitle=a.output/'recording-captions.ass';subtitle.write_text(ass,encoding='utf-8')
try:
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(a.input/'studio-tour.webm'),'-vf','ass=recording-captions.ass','-an','-r','12','-c:v','libx264','-preset','medium','-crf','26','-pix_fmt','yuv420p','-movflags','+faststart',str(a.output/'screencast.mp4')],cwd=a.output,check=True)
finally:subtitle.unlink(missing_ok=True)
assets=a.output/'assets';assets.mkdir(exist_ok=True)
for name in ('pressure','flood','peer'):shutil.copyfile(a.input/(name+'.png'),assets/(name+'.png'))
shutil.copyfile(a.input/'map-forest.png',assets/'scene.png')
for name in ('map-forest','map-quarry','map-city','map-snow','map-delta','studio-editor','studio-mission','studio-live','decisions','journal','forest-current','apartment-tour','apartment-operation','apartment-decisions','apartment-branches'):
    source=a.input/(name+'.png')
    if source.exists():shutil.copyfile(source,assets/(name+'.png'))
print(json.dumps({'status':'passed','output':str(a.output),'caption_count':len(rows),'visible_captions':True}))

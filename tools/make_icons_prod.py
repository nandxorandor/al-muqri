"""Write all launcher icon densities for Al-Muqri into the Android res tree."""
from PIL import Image, ImageDraw
import math, os, sys

RES = sys.argv[1]  # .../app/src/main/res
GREEN1=(18,40,29); GREEN2=(8,19,13); GREEN_DK=(9,22,15); BG_FLAT=(18,40,29)
GOLD=(233,197,55); SS=4

def gradient_bg(sz):
    im=Image.new("RGBA",(sz,sz),(0,0,0,0)); d=ImageDraw.Draw(im)
    for y in range(sz):
        t=y/sz
        d.line([(0,y),(sz,y)],fill=(int(GREEN1[0]*(1-t)+GREEN2[0]*t),
                                    int(GREEN1[1]*(1-t)+GREEN2[1]*t),
                                    int(GREEN1[2]*(1-t)+GREEN2[2]*t),255))
    return im

def sq(cx,cy,half,ang):
    pts=[]; r=half*math.sqrt(2)
    for a in (45,135,225,315):
        rad=math.radians(a+ang); pts.append((cx+r*math.cos(rad),cy+r*math.sin(rad)))
    return pts

def symbol(sz):
    """Gold open mushaf on transparent, centred, sized to fit a circle."""
    im=Image.new("RGBA",(sz,sz),(0,0,0,0)); d=ImageDraw.Draw(im)
    cx=sz//2; S=sz/1024.0
    by=int(512*S)                                   # vertically centred
    top=(cx,by-int(215*S)); bot=(cx,by+int(200*S))
    L=[top,(cx-int(390*S),by-int(120*S)),(cx-int(410*S),by+int(205*S)),bot]
    R=[top,(cx+int(390*S),by-int(120*S)),(cx+int(410*S),by+int(205*S)),bot]
    d.polygon(L,fill=GOLD); d.polygon(R,fill=GOLD)
    for i in range(5):                              # page (text) lines
        yy=by-int(120*S)+i*int(62*S); outl=int(340*S)-i*int(10*S); inl=int(42*S)
        d.line([(cx-outl,yy+int(40*S)),(cx-inl,yy)],fill=GREEN_DK,width=max(3,int(13*S)))
        d.line([(cx+inl,yy),(cx+outl,yy+int(40*S))],fill=GREEN_DK,width=max(3,int(13*S)))
    d.line([top,bot],fill=GREEN_DK,width=max(3,int(12*S)))
    return im

MASTER = symbol(1024*SS)  # hi-res symbol, downscaled when pasted

def paste_scaled(canvas, frac):
    sz=canvas.size[0]; target=int(sz*frac)
    sym=MASTER.resize((target,target),Image.LANCZOS)
    canvas.alpha_composite(sym,((sz-target)//2,(sz-target)//2))
    return canvas

def full(sz):   # legacy square icon: gradient bg + symbol
    im=gradient_bg(sz*SS); paste_scaled(im,0.74); return im.resize((sz,sz),Image.LANCZOS)
def rnd(sz):    # legacy round icon: circular-masked
    im=full(sz*1).convert("RGBA")
    # build at SS for AA circle
    big=gradient_bg(sz*SS); paste_scaled(big,0.74)
    mask=Image.new("L",(sz*SS,sz*SS),0); ImageDraw.Draw(mask).ellipse([0,0,sz*SS,sz*SS],fill=255)
    big.putalpha(mask); return big.resize((sz,sz),Image.LANCZOS)
def fg(sz):     # adaptive foreground: transparent + symbol in safe zone
    im=Image.new("RGBA",(sz*SS,sz*SS),(0,0,0,0)); paste_scaled(im,0.62)
    return im.resize((sz,sz),Image.LANCZOS)

# density -> (launcher size, foreground size)
DENS={"mdpi":(48,108),"hdpi":(72,162),"xhdpi":(96,216),"xxhdpi":(144,324),"xxxhdpi":(192,432)}
for d,(ls,fs) in DENS.items():
    p=os.path.join(RES,f"mipmap-{d}"); os.makedirs(p,exist_ok=True)
    full(ls).save(os.path.join(p,"ic_launcher.png"))
    rnd(ls).save(os.path.join(p,"ic_launcher_round.png"))
    fg(fs).save(os.path.join(p,"ic_launcher_foreground.png"))
    print("wrote",d)

# adaptive background color -> deep green
bgxml=os.path.join(RES,"values","ic_launcher_background.xml")
open(bgxml,"w",encoding="utf-8").write(
    '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
    f'    <color name="ic_launcher_background">#{BG_FLAT[0]:02X}{BG_FLAT[1]:02X}{BG_FLAT[2]:02X}</color>\n'
    '</resources>\n')
full(512).save(os.path.join(os.path.dirname(__file__),"preview_book.png"))
print("done; bg color set")

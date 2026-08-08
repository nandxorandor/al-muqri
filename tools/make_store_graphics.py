"""Generate Google Play store graphics: 512x512 icon + 1024x500 feature graphic."""
from PIL import Image, ImageDraw, ImageFont
import math, os, sys
import arabic_reshaper
from bidi.algorithm import get_display

OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
GREEN1=(18,40,29); GREEN2=(8,19,13); GREEN_DK=(9,22,15); GOLD=(233,197,55); GOLD_LT=(245,224,130)
ARABIC_FONT="C:/Windows/Fonts/trado.ttf"   # Traditional Arabic (elegant)
LATIN_FONT="C:/Windows/Fonts/georgiab.ttf"
SS=4

def grad(w,h):
    im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    for y in range(h):
        t=y/h
        d.line([(0,y),(w,y)],fill=(int(GREEN1[0]*(1-t)+GREEN2[0]*t),
                                   int(GREEN1[1]*(1-t)+GREEN2[1]*t),
                                   int(GREEN1[2]*(1-t)+GREEN2[2]*t),255))
    return im

def book(sz):
    """gold open mushaf on transparent, centred (same as app icon)."""
    im=Image.new("RGBA",(sz,sz),(0,0,0,0)); d=ImageDraw.Draw(im); cx=sz//2; S=sz/1024.0
    by=int(512*S); top=(cx,by-int(215*S)); bot=(cx,by+int(200*S))
    L=[top,(cx-int(390*S),by-int(120*S)),(cx-int(410*S),by+int(205*S)),bot]
    R=[top,(cx+int(390*S),by-int(120*S)),(cx+int(410*S),by+int(205*S)),bot]
    d.polygon(L,fill=GOLD); d.polygon(R,fill=GOLD)
    for i in range(5):
        yy=by-int(120*S)+i*int(62*S); outl=int(340*S)-i*int(10*S); inl=int(42*S)
        d.line([(cx-outl,yy+int(40*S)),(cx-inl,yy)],fill=GREEN_DK,width=max(3,int(13*S)))
        d.line([(cx+inl,yy),(cx+outl,yy+int(40*S))],fill=GREEN_DK,width=max(3,int(13*S)))
    d.line([top,bot],fill=GREEN_DK,width=max(3,int(12*S)))
    return im

def ar(txt):
    return get_display(arabic_reshaper.reshape(txt))

# ---- 512x512 store icon (full-bleed, no transparency) ----
ic=grad(512*SS,512*SS); ic.alpha_composite(book(512*SS).resize((int(512*SS*0.74),)*2,Image.LANCZOS),
                                    (int(512*SS*0.13),int(512*SS*0.13)))
ic.convert("RGB").resize((512,512),Image.LANCZOS).save(os.path.join(OUT,"play-icon-512.png"))
print("wrote play-icon-512.png")

# ---- 1024x500 feature graphic ----
W,H=1024*SS,500*SS
fg=grad(W,H); d=ImageDraw.Draw(fg)
# book on the right third
bk=book(int(H*0.9)); fg.alpha_composite(bk,(int(W*0.66),int(H*0.05)))
# subtle gold divider
# text on the left
f_ar=ImageFont.truetype(ARABIC_FONT,int(150*SS))
f_lat=ImageFont.truetype(LATIN_FONT,int(96*SS))
f_sub=ImageFont.truetype(LATIN_FONT,int(38*SS))
x=int(60*SS); y=int(70*SS)
d.text((x,y), ar("المقرئ"), font=f_ar, fill=GOLD_LT)
d.text((x,y+int(175*SS)), "Al-Muqri", font=f_lat, fill=(233,239,233))
d.text((x,y+int(300*SS)), "Qur'an recitation feedback — on your phone", font=f_sub, fill=(180,200,185))
fg.convert("RGB").resize((1024,500),Image.LANCZOS).save(os.path.join(OUT,"feature-graphic-1024x500.png"))
print("wrote feature-graphic-1024x500.png")

from PIL import Image, ImageDraw, ImageFont,ImageOps
from pathlib import Path
assets=Path(__file__).resolve().parent/'assets'
im=ImageOps.fit(Image.open(assets/'portrait.png').convert('RGB'),(544,544));d=ImageDraw.Draw(im);ink='#161616';acid='#FFFA00';d.polygon([(0,0),(205,0),(205,44),(194,55),(0,55)],fill=ink);d.rectangle((0,0,8,54),fill=acid);d.text((17,4),'RCBridge',fill='#F4F4F2',font=ImageFont.truetype('arialbd.ttf',38));d.polygon([(420,510),(544,510),(544,544),(400,544)],fill=acid);d.text((436,514),'RC / BR',fill=ink,font=ImageFont.truetype('arialbd.ttf',19));im.save(assets/'icon.png');im.save(assets/'icon.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])

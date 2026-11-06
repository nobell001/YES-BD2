"""How large a picture text is read from.

0 = as captured, never shrunk first.  Text used to be read from the frame
shrunk to 720 high (ok-script target height 720); on a 2560x1440 繁中
game that halves every character, and multi-stroke ones came back wrong:
戰鬥→戰門, 經營→經营, 地下祕密拍賣場→地下部密拍周場, 卡帶→卡带 (4K PC
2026-11-06 frames, each read both ways).  At the captured size they read
right, and no slower: the text finder shrinks to 960 wide by itself
(onnxocr det_limit_side_len), only the word reader sees the extra detail.
"""

READ_HEIGHT = 0

"""쉬운 말 문장을 만들 때 쓰는 한국어 규칙."""

# 영문·숫자를 한국어로 읽었을 때 받침이 있는 끝 글자
# (L=엘, M=엠, N=엔, R=알, 0=영, 1=일, 3=삼, 6=육, 7=칠, 8=팔)
_FINAL_CONSONANT = set("LMNR013678")


def has_batchim(word: str) -> bool:
    ch = word.strip()[-1:] or "a"
    if "가" <= ch <= "힣":
        return (ord(ch) - ord("가")) % 28 != 0
    return ch.upper() in _FINAL_CONSONANT

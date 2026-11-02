# 글꼴 파일

대시보드는 바깥 요청 없이 이 폴더의 파일만 쓴다. 파일은 git에 넣지 않는다(.gitignore). 없으면 아래 명령으로 받는다. 출처는 모두 공개 라이선스(OFL)다.

```
curl -L -o PretendardVariable.woff2 https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/woff2/PretendardVariable.woff2
curl -L -o SUIT-Variable.woff2 https://cdn.jsdelivr.net/gh/sunn-us/SUIT/fonts/variable/woff2/SUIT-Variable.woff2
curl -L -o WantedSansVariable.woff2 https://cdn.jsdelivr.net/npm/wanted-sans@1.0.3/fonts/webfonts/variable/complete/woff2/WantedSansVariable.woff2
for w in 400 500 700: curl -L -o ibm-plex-sans-kr-korean-$w.woff2 https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans-kr@5.2.5/files/ibm-plex-sans-kr-korean-$w-normal.woff2
                      curl -L -o ibm-plex-sans-kr-latin-$w.woff2  https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans-kr@5.2.5/files/ibm-plex-sans-kr-latin-$w-normal.woff2
for w in 400 700:     curl -L -o ibm-plex-mono-latin-$w.woff2 https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.2.5/files/ibm-plex-mono-latin-$w-normal.woff2
```

고정폭 글꼴 JetBrains Mono, Cascadia Mono, Fira Code, Consolas는 이 컴퓨터에 설치되어 있어 파일이 필요 없다.

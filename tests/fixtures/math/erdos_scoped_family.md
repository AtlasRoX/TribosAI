1. Since $n\equiv3\pmod4$, write $n=4m+3$ for an integer $m$. Then $k=(n-3)/4=m$ is an integer. From $n\ge3$, $4m+3\ge3$, so $m\ge0$. Hence $k$ is a nonnegative integer. Then $x=k+1=m+1\ge1$ is a positive integer, and $y=z=2(k+1)n$ is a product of positive integers. In fact $x=(n+1)/4$ and $y=z=n(n+1)/2$.

2. By definition $y=z$, so $y\le z$ with equality. Moreover $y=2nx$, since $y=2(k+1)n$ and $x=k+1$. Since $n\ge3$ and $x>0$, $y-x=(2n-1)x>0$. Hence $x<y$, in particular $x\le y\le z$.

3. With $x=k+1$ and $y=z=2(k+1)n$,
$$\frac1x+\frac1y+\frac1z=\frac1{k+1}+\frac1{2(k+1)n}+\frac1{2(k+1)n}=\frac1{k+1}+\frac1{(k+1)n}=\frac{n+1}{(k+1)n}.$$
Since $k=(n-3)/4$, $k+1=(n+1)/4$, i.e. $n+1=4(k+1)$. Substituting gives
$$\frac1x+\frac1y+\frac1z=\frac{4(k+1)}{(k+1)n}=\frac4n.$$
This holds for every $n\ge3$ and $n\equiv3\pmod4$.

4. For $n=3$, $k=(3-3)/4=0$, so $x=1$, $y=6$, $z=6$, and $1+1/6+1/6=4/3$. For $n=7$, $k=(7-3)/4=1$, so $x=2$, $y=28$, $z=28$, and $1/2+1/28+1/28=4/7$. This does not prove the full conjecture; it only covers the stated congruence class.

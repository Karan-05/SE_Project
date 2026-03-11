def solve(n):
                if n < 2:
                    return 0
                sieve = [True]*(n+1)
                sieve[0]=sieve[1]=False
                p=2
                while p*p<=n:
                    if sieve[p]:
                        for m in range(p*p,n+1,p):
                            sieve[m]=False
                    p+=1
                return sum(sieve)

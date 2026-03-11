def solve(coins, amount):
                dp = [float('inf')] * (amount + 1)
                dp[0] = 0
                for coin in coins:
                    for value in range(coin, amount + 1):
                        dp[value] = min(dp[value], dp[value - coin] + 1)
                return dp[amount] if dp[amount] != float('inf') else -1

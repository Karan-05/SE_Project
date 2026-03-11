def solve(value):
                result = {}
                for ch in value:
                    result[ch] = result.get(ch, 0) + 1
                return dict(sorted(result.items()))

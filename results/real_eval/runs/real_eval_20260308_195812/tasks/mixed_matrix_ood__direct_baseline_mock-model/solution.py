def solve(matrix):
                return sum(matrix[i][i] for i in range(min(len(matrix), len(matrix[0]))))

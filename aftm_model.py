"""
AFTM reliability model functions
R(t,L) = exp(-lambda * t * L^alpha)
F(t,L) = 1 - R(t,L)
lambda(L) = lambda_base * L^alpha
"""
import math

def lambda_L(base_lambda, L, alpha=1.0):
    return base_lambda * (L ** alpha)


def reliability_R(t, L, base_lambda, alpha=1.0):
    """Return reliability R(t,L) = exp(-base_lambda * t * L^alpha)"""
    lam = lambda_L(base_lambda, L, alpha)
    # Protect against negative or zero
    if t < 0:
        raise ValueError("Time t must be non-negative")
    return math.exp(-lam * t)


def failure_F(t, L, base_lambda, alpha=1.0):
    return 1.0 - reliability_R(t, L, base_lambda, alpha)


if __name__ == "__main__":
    print(reliability_R(1000, 10, 3e-6))
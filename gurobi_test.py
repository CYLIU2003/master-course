import gurobipy as gp
from gurobipy import GRB

m = gp.Model("test")
x = m.addVar(vtype=GRB.BINARY, name="x")
y = m.addVar(vtype=GRB.BINARY, name="y")
z = m.addVar(vtype=GRB.BINARY, name="z")

m.setObjective(x + y + 2*z, GRB.MAXIMIZE)
m.addConstr(x + 2*y + 3*z <= 4)
m.addConstr(x + y >= 1)

m.optimize()

for v in m.getVars():
    print(v.VarName, v.X)
print("Obj =", m.ObjVal)
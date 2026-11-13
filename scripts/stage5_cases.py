"""Frozen stage-5 condition family, separate from controller code."""

def parameters(name):
    p={'profile':'rescue_v2','layout':'floodplain','max_steps':180,'events':[],'cohorts':1,'targets_per_kind':1}
    if name in ('flood_team','flood_faults'):p.update(cohorts=2,targets_per_kind=2)
    if name=='flood_faults':p['events']=[
        {'time':3.,'type':'agent_degradation','targets':['boat'],'parameters':{}},
        {'time':4.,'type':'restricted_zone_appeared','targets':[],'parameters':{'min':[68.,20.,-15.],'max':[70.,24.,0.]}},
        {'time':5.,'type':'infrastructure_failure','targets':['infra_0'],'parameters':{}},
        {'time':7.,'type':'stale_information','targets':[],'parameters':{}},
        {'time':8.,'type':'agent_failure','targets':['land'],'parameters':{}},
        {'time':9.,'type':'contradictory_information','targets':[],'parameters':{}}]
    return p

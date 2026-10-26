"""Small external memory environments, independent of core hardware YAMLs."""
import json
from pathlib import Path
import yaml


def port(latency=1):
    return dict(grant_pattern=[1],response_cycles=[latency],cache=dict(lines=0,line_bytes=16,hit_cycles=1,miss_cycles=latency))


def validate(value):
    if not isinstance(value,dict) or set(value)!={'imem','dmem'}:
        raise ValueError('memory environment requires exactly imem and dmem')
    out={}
    for name,p in value.items():
        if not isinstance(p,dict) or set(p)!={'grant_pattern','response_cycles','cache'}:
            raise ValueError(name+': expected grant_pattern, response_cycles and cache')
        grants=p['grant_pattern'];responses=p['response_cycles'];c=p['cache']
        if not isinstance(grants,list) or not 1<=len(grants)<=64 or not any(grants) or any(type(x) is not int or x not in (0,1) for x in grants):
            raise ValueError(name+': grant_pattern must contain 1..64 binary slots and a grant')
        if not isinstance(responses,list) or not 1<=len(responses)<=64 or any(type(x) is not int or not 1<=x<=254 for x in responses):
            raise ValueError(name+': response_cycles must contain 1..64 positive byte delays')
        if not isinstance(c,dict) or set(c)!={'lines','line_bytes','hit_cycles','miss_cycles'}:
            raise ValueError(name+': invalid cache fields')
        if any(type(x) is not int for x in c.values()) or c['lines'] not in (0,1,2,4,8,16,32,64,128,256) or c['line_bytes'] not in (4,8,16,32,64) or not 1<=c['hit_cycles']<=c['miss_cycles']<=254:
            raise ValueError(name+': invalid direct-mapped cache geometry/latency')
        out[name]=dict(grant_pattern=grants[:],response_cycles=responses[:],cache=dict(c))
    return out


def load(path=None,imem=1,dmem=1):
    return validate(yaml.safe_load(Path(path).read_text()) if path else dict(imem=port(imem),dmem=port(dmem)))


def parameters(p,prefix):
    # Flat integer parameters fit CorePerfDSL bindings and canonical identities.
    result={prefix+'.grant_length':len(p['grant_pattern']),prefix+'.response_length':len(p['response_cycles'])}
    result.update({prefix+'.grants['+str(i)+']':x for i,x in enumerate(p['grant_pattern'])})
    result.update({prefix+'.responses['+str(i)+']':x for i,x in enumerate(p['response_cycles'])})
    result.update({prefix+'.'+k:v for k,v in p['cache'].items()})
    return result


def cpp_configuration(p,instance):
    def array(values):return '{'+','.join(map(str,values))+'}'
    c=p['cache']
    return (f'{instance}.configure({array(p["grant_pattern"])},{array(p["response_cycles"])},'
            f'{c["lines"]},{c["line_bytes"]},{c["hit_cycles"]},{c["miss_cycles"]});')

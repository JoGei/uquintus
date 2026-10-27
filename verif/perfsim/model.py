"""Translate validated uquintus settings into generated timing-model inputs."""
import hashlib
import json
from pathlib import Path
from memory import load as load_memory,validate as validate_memory,parameters as memory_parameters

ROOT = Path(__file__).resolve().parents[2]
MODEL_VERSION = 'uqu-five-stage-admission-v5'
MAP_MODEL_VERSION = 'uqu-map-dse-v8'
FORWARD_PATHS = ('MUA_FORWARD_EX_TO_DE', 'MUA_FORWARD_MEM_TO_DE',
                 'MUA_FORWARD_MEM_TO_EX', 'MUA_FORWARD_WB_TO_EX')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def describe(config, imem_latency=1, dmem_latency=1, catalog=None, contract="queue", memory=None):
    if contract not in ("queue", "map_dse"):
        raise ValueError("unknown timing-model contract")
    """Fail closed outside the first, deliberately limited model profile."""
    for name in ('ISA_ZFINX', 'ISA_F', 'ISA_A',
                 'ISA_ZIFENCEI', 'XIF', 'DEBUG', 'MUA_HARDENED'):
        if config[name]:
            raise ValueError(f'{name}=1 is outside the initial integer perfsim profile')
    if contract=='queue' and (config['ISA_E'] or config['ISA_PMP']):
        raise ValueError('ISA_E/ISA_PMP require map_dse')
    if config['ISA_PMP'] and (config['MUA_BTB']!='none' or config['MUA_BRANCH_PREDICTOR']!='none'):
        raise ValueError('PMP timing initially requires prediction disabled')
    if contract=='queue' and config['MUA_BTB'] != 'none':
        raise ValueError('BTB address/replay timing is not yet modeled')
    if config['MUA_BRANCH_PREDICTOR'] not in (('none','static_not_taken','bimodal') if contract=='map_dse' else ('none','static_not_taken')):
        raise ValueError('initial perfsim supports none/static_not_taken prediction')
    fine = bool(config['MUA_FORWARDING'] and not all(config[p] for p in FORWARD_PATHS))
    if contract=='queue' and fine:
        raise ValueError('fine forwarding requires the map_dse contract; queue is a retained legacy reference')
    if contract=='queue' and memory is not None:
        raise ValueError('external memory environments require map_dse')
    memory=validate_memory(memory) if memory is not None else (load_memory(imem=imem_latency,dmem=dmem_latency) if contract=='map_dse' else None)
    for value in (imem_latency, dmem_latency):
        if type(value) is not int or not 1 <= value <= 10000:
            raise ValueError('memory response latency must be an integer from 1 through 10000')
    if contract == "map_dse" and not (1 <= imem_latency <= 254 and 1 <= dmem_latency <= 254):
        raise ValueError("MAP-DSE fetch latency must be 1..254 (upstream 8-bit delay vectors)")
    if config['ISA_PMP'] and memory['imem']!=load_memory()['imem']:
        raise ValueError('PMP fetch-fault timing currently requires one-cycle immediate-grant imem without a cache')
    factor = config['MUA_MULDIV_ITERUNROLL']
    split = bool(config['ISA_M'] and config['MUA_MUL'] == 'dadda_mac')
    mul_cycles = 32 // factor if config['MUA_MUL'] == 'iterative' else 1
    div_cycles = 1 if config['MUA_DIV'] == 'parallel' else (2 + factor - 1) // factor + 32 // factor + 1
    schedule = dict(version=MODEL_VERSION, isa_m=config['ISA_M'], isa_c=config['ISA_C'],
                    isa_e=config['ISA_E'], isa_pmp=config['ISA_PMP'],
                    forwarding=config['MUA_FORWARDING'], split_mul=split,
                    fine_forwarding=fine,
                    forward_ex_to_de=bool(config['MUA_FORWARDING'] and config['MUA_FORWARD_EX_TO_DE']),
                    forward_mem_to_de=bool(config['MUA_FORWARDING'] and config['MUA_FORWARD_MEM_TO_DE']),
                    forward_mem_to_ex=bool(config['MUA_FORWARDING'] and config['MUA_FORWARD_MEM_TO_EX']),
                    forward_wb_to_ex=bool(config['MUA_FORWARDING'] and config['MUA_FORWARD_WB_TO_EX']),
                    operand_retention=bool(fine and config['MUA_DE_OPERAND_RETENTION']),
                    mul_cycles=mul_cycles if config['ISA_M'] else 1,
                    div_cycles=div_cycles if config['ISA_M'] else 1,
                    predictor=config['MUA_BRANCH_PREDICTOR'],
                    btb=config['MUA_BTB'] if config['MUA_BRANCH_PREDICTOR']!='none' else 'none',
                    bp_entries=config['MUA_BP_ENTRIES'] if config['MUA_BRANCH_PREDICTOR']=='bimodal' and config['MUA_BTB']!='none' else 16,
                    btb_entries=config['MUA_BTB_ENTRIES'] if config['MUA_BRANCH_PREDICTOR']!='none' and config['MUA_BTB']!='none' else 16,
                    idata_hwords=config['MUA_BTB_IDATA_HWORDS'] if config['MUA_BRANCH_PREDICTOR']!='none' and config['MUA_BTB']!='none' else 0,
                    if_buffer_words=config['MUA_IF_BUFFER_WORDS'],
                    redirect_bypass=config['MUA_REDIRECT_BYPASS'],
                    imem_latency=imem_latency, dmem_latency=dmem_latency)
    if catalog is None:
        catalog = json.loads((ROOT/'config/selectors.json').read_text())
    external_models = {
        'frontendModel': dict(implementation='uqu/FrontendModel.h', parameters=dict(
            static_not_taken=schedule['predictor'] == 'static_not_taken', compressed=bool(config['ISA_C']),
            imem_latency=imem_latency, buffer_words=schedule['if_buffer_words'],
            bypass=catalog['MUA_REDIRECT_BYPASS'][schedule['redirect_bypass']]['value'])),
        'regModel': dict(implementation='uqu/RegisterModel.h', parameters=dict(forwarding=bool(config['MUA_FORWARDING']))),
        'serialModel': dict(implementation='uqu/SerialModel.h', parameters={}),
    }
    if contract == 'map_dse':
        schedule = dict(schedule, version=MAP_MODEL_VERSION, contract=contract)
        bypass = catalog['MUA_REDIRECT_BYPASS'][schedule['redirect_bypass']]['value']
        external_models['frontendModel'] = dict(implementation='uqu/TraceBranchModel.h', parameters=dict(
            recovery_cycles=3-int(bypass).bit_count()))
        external_models['fetchModel'] = dict(implementation='uqu/TraceFetchModel.h', parameters=dict(
            latency=imem_latency,static_not_taken=schedule['predictor']!='none',
            compressed=bool(config['ISA_C']),buffer_words=schedule['if_buffer_words'],bypass=bypass,
            dmem_latency=dmem_latency,mul_cycles=schedule['mul_cycles'],div_cycles=schedule['div_cycles'],
            split_mul=split,forwarding=bool(config['MUA_FORWARDING']),
            predictor=catalog['MUA_BRANCH_PREDICTOR'][schedule['predictor']]['value'],
            btb=schedule['btb']=='direct_mapped',bp_entries=schedule['bp_entries'],
            btb_entries=schedule['btb_entries'],idata_hwords=schedule['idata_hwords'],
            **{k:schedule[k] for k in ('fine_forwarding','forward_ex_to_de','forward_mem_to_de','forward_mem_to_ex','forward_wb_to_ex','operand_retention')}))
        external_models['fetchModel']['parameters'].update(memory_profile=True,
            **memory_parameters(memory['imem'],'imem'),**memory_parameters(memory['dmem'],'dmem'))
        external_models['hazardModel']=dict(implementation='uqu/TraceHazardModel.h',parameters={})
        external_models['requestModel']=dict(implementation='uqu/TraceRequestModel.h',parameters={})
        external_models['responseModel']=dict(implementation='uqu/TraceResponseModel.h',parameters={})
    ident = fingerprint(dict(schedule=schedule, external_models=external_models))
    coverage = {key: 'recorded_inactive' for key in config}
    for key in ('ISA_E','ISA_M', 'ISA_C', 'MUA_FORWARDING', 'MUA_BRANCH_PREDICTOR'):
        coverage[key] = 'modeled_uncalibrated'
    if config['ISA_M']:
        for key in ('MUA_MUL', 'MUA_DIV', 'MUA_MULDIV_ITERUNROLL'):
            coverage[key] = 'modeled_uncalibrated'
        if config['MUA_MUL'] != 'iterative' and config['MUA_DIV'] != 'iterative':
            coverage['MUA_MULDIV_ITERUNROLL'] = 'recorded_inactive'
    for key in ('MUA_IF_BUFFER_WORDS', 'MUA_REDIRECT_BYPASS'):
        coverage[key] = 'modeled_frontend_queues'
    if config['ISA_C']:
        for key in ('MUA_C_IMPL', 'MUA_C_DECOMPRESS_STAGE'):
            coverage[key] = 'assumed_cycle_equivalent'
    coverage['HART_ID'] = 'functional_constant'
    coverage['ISA_UMODE'] = 'synchronous_M_U_adapter' if contract=='map_dse' else 'M_mode_execution_only'
    coverage['ISA_PMP'] = 'architectural_permission_checks_uncalibrated' if config['ISA_PMP'] else 'recorded_inactive'
    for key in ('MUA_REGFILE_IMPL', 'MUA_DE_OPERAND_RETENTION'):
        coverage[key] = 'assumed_cycle_equivalent'
    for key in FORWARD_PATHS:
        coverage[key] = 'producer_availability_windows' if config['MUA_FORWARDING'] else 'recorded_inactive'
    if contract == 'map_dse':
        coverage['MUA_IF_BUFFER_WORDS'] = 'trace_driven_queue_envelope'
        coverage['MUA_DE_OPERAND_RETENTION'] = 'producer_window_retention' if fine else 'cycle_equivalent_in_supported_forwarding_profile'
        coverage['MUA_REDIRECT_BYPASS'] = 'modeled_frontend_queues'
        if schedule['btb']!='none':
            for key in ('MUA_BTB','MUA_BTB_ENTRIES','MUA_BTB_IDATA_HWORDS'):
                coverage[key]='reference_clocked_bpu_model'
            if schedule['predictor']=='bimodal':coverage['MUA_BP_ENTRIES']='reference_clocked_bpu_model'
    return dict(name='UQU_' + ident[:16].upper(), id=ident, schedule=schedule,
                memory_environment=memory,
                external_models=external_models,
                status='uncalibrated', coverage=coverage,
                approximations=([
                    'trace-driven finite frontend queues for none/static-not-taken/bimodal policies',
                    'reference EX/MEM/WB occupancy and operand-admission calendar; no scheduled-core timestamp feedback',
                    'tagged direction/target state and packed replay prefixes use reference-clocked IF capture and DE training',
                    'IF prediction held across DE backpressure; ordered periodic-grant/address-latency memory or tag-only cache stubs',
                    'independent forwarding paths and finite producer windows; reference-clocked operand retention' ] if contract=='map_dse' else
                   ['16/32-bit aligned ordered OBI frontend; immediate grants, fixed response latency, no BTB/replay',
                                'aggregate forwarding availability; no partial paths',
                                'ASAP pipeline/backpressure; RTL calibration required']))


def render(description):
    s = description['schedule']
    # An unchanged Architecture/trace schema allows multiple generated models
    # to consume the same ETISS channel in one native process.
    early_alu = ' -> Xd' if s['forwarding'] else ''
    early_mul = ' -> Xd' if s['forwarding'] and not s['split_mul'] else ''
    early_finish = ' -> Xd' if s['forwarding'] and s['split_mul'] else ''
    alu_wb = '' if s['forwarding'] else ', uWrite'
    values = dict(NAME=description['name'], IMEM=s['imem_latency'], DMEM=s['dmem_latency'],
                  MUL=s['mul_cycles'], DIV=s['div_cycles'], ALU_OUT=early_alu,
                  MUL_OUT=early_mul, FINISH_OUT=early_finish, WRITE=alu_wb,
                  MUL_FINISH=', uFinish' if s['split_mul'] else '')
    values.update(FRONTEND_MODEL=description['external_models']['frontendModel']['implementation'],
                  REGISTER_MODEL=description['external_models']['regModel']['implementation'],
                  SERIAL_MODEL=description['external_models']['serialModel']['implementation'])
    text = (ROOT/'verif/perfsim/models/uqu.corePerfDsl.in').read_text()
    for key, value in values.items():
        text = text.replace('@'+key+'@', str(value))
    text = text.replace('TraceValue {pc, code, rs1, rs2, rd, brTarget}', 'TraceValue {pc, code, rs1, rs2, rd, brTarget, memAddr}')
    text = text.replace('[ALL]: {pc="$resolved{$pc}", code="$code"}', '[ALL]: {pc="$resolved{$pc}", code="$code", memAddr="0"}')
    if s.get('contract') == 'map_dse':
        text = text.replace('Pc_np, IfConsumed, DeAdvanced,', 'Pc_np, AdmissionBase, RequestBase,')
        text = text.replace('TraceValue {pc, code, rs1, rs2, rd, brTarget}', 'TraceValue {pc, code, rs1, rs2, rd, brTarget, memAddr}')
        text = text.replace('[ALL]: {pc="$resolved{$pc}", code="$code"}', '[ALL]: {pc="$resolved{$pc}", code="$code", memAddr="0"}')
        text = text.replace('Request, Response('+str(s['dmem_latency'])+')', 'Request(requestModel), Response(responseModel)')
        text = text.replace('uRequest(Request)', 'uRequest(RequestBase -> Request)')
        text = text.replace('OperandWait(0)', 'OperandWait(0), Admission(hazardModel)')
        text = text.replace('  uFetch(Pc -> Fetch),', '  uAdmit(AdmissionBase -> Admission), uFetch(Pc -> Fetch),')
        text = text.replace('DE_stage(uDelivery,', 'DE_stage(uAdmit, uDelivery,')
        text = text.replace('[ALL]: {uFetch,', '[ALL]: {uAdmit, uFetch,')
        text = text.replace('connectorIn: {Serial, Committed} connectorOut: {Serial, Committed}',
                            'connectorIn: {Serial, Committed} connectorOut: {Serial, Committed, AdmissionBase, RequestBase}')
        if s['fine_forwarding']:
            # Source lifetime/route choices come from the hazard resource. A
            # monotonic register-ready timestamp cannot represent missed paths.
            for old,new in [('Da -> OperandWait','OperandWait'),('{Da, Db} -> OperandWait','OperandWait'),
                            ('{Xa, Xb} -> ALU','ALU'),('Xa -> ALU','ALU'),
                            ('{Xa, Xb} -> Mul','Mul'),('{Xa, Xb} -> Div','Div'),
                            ('{Da, Db} -> Branch','Branch'),('Da -> Branch','Branch'),('Xa -> CsrRead','CsrRead')]:
                text=text.replace(old,new)
        # RTL serializes younger admission after a CSR/MRET/fence enters EX;
        # it does not wait in DE for all older ordinary instructions to retire.
        text=text.replace('uRead1, uCsrDrain, uCsrA','uRead1, uCsrA').replace('CsrImm: {uCsrDrain,','CsrImm: {')
        text=text.replace('Fences: {uCsrDrain, ','Fences: {')
        text = text.replace('Fetch(0)', 'Fetch(fetchModel)')
        # Canonical timing event types retain the original PC/encoding in the
        # channel. Faults are classified by discovery stage by the ISA adapter.
        text=text.replace('Default([?])','EventDecode(ecall), EventMemory(ebreak), EventFetch(wfi), Returns(mret), Default([?])')
        text=text.replace('uRX(ALU', 'uPass(ALU), uRX(ALU')
        text=text.replace('uRR, uRI, uRX,', 'uRR, uRI, uRX, uPass,')
        text=text.replace('uFence(CSR -> Serial)','uFence(CSR -> Serial), uEvent(CSR -> {Serial, Pc_np})')
        text=text.replace('uCsrResult, uFence)', 'uCsrResult, uFence, uEvent)')
        text=text.replace('Fences: {uFence}', 'EventDecode: {uRead2, uPass, uEvent}, EventMemory: {uRead2, uStoreAddr, uEvent}, EventFetch: {uPass, uEvent}, Returns: {uPass, uEvent}, Fences: {uFence}')
        text=text.replace('CsrReg: {uRead1,', 'CsrReg: {uPass, uRead1,').replace('CsrImm: { uCsrResult}', 'CsrImm: {uPass, uCsrResult}')
        text=text.replace('Fences: {uFence}', 'Fences: {uPass, uFence}').replace('Branches: {uBranch2}', 'Branches: {uPass, uBranch2}').replace('CBranches: {uBranch1}', 'CBranches: {uPass, uBranch1}')
        text=text.replace('brTarget, memAddr}', 'brTarget, memAddr, event}')
        text=text.replace('memAddr="0"}', 'memAddr="0", event="0"}')
        text = text.replace('Delivery -> IfConsumed', 'Delivery').replace('FrontAdvance -> DeAdvanced', 'FrontAdvance')
        text = text.replace('  connectorIn: {Pc_p, Pc_np, IfConsumed, DeAdvanced} connectorOut: Pc',
                            '  connectorIn: {Pc_p, Pc_np} connectorOut: Pc')
        text = text.replace('ConnectorModel serialModel(',
                            'ResourceModel fetchModel(link: "uqu/TraceFetchModel.h" trace: {pc, code, rs1, rs2, rd, brTarget, memAddr, event})\nResourceModel hazardModel(link: "uqu/TraceHazardModel.h" trace: {pc})\nResourceModel requestModel(link: "uqu/TraceRequestModel.h" trace: {pc})\nResourceModel responseModel(link: "uqu/TraceResponseModel.h" trace: {pc})\nConnectorModel serialModel(')
    return text


def render_external_bindings(description, instance='m'):
    """Use the resolved plan for both inspection and actual native bindings."""
    lines = []
    for name, model in description['external_models'].items():
        for parameter, value in model['parameters'].items():
            if type(value) is bool:
                literal = 'true' if value else 'false'
            elif type(value) is int and value >= 0:
                literal = str(value)
            else:
                raise ValueError(f'unsupported external-model value {name}.{parameter}: {value!r}')
            lines.append(f'{instance}->{name}.{parameter}={literal};')
    if description['schedule'].get('contract')=='map_dse':
        lines.append(f'{instance}->hazardModel.source=&{instance}->fetchModel;')
        lines.append(f'{instance}->requestModel.source=&{instance}->fetchModel;')
        lines.append(f'{instance}->responseModel.source=&{instance}->fetchModel;')
        lines.append(f'{instance}->serialModel.if_stage_ptr=&{instance}->IF_stage;')
        lines.append(f'{instance}->serialModel.ex_stage_ptr=&{instance}->EX_stage;')
        lines.append(f'{instance}->serialModel.wb_stage_ptr=&{instance}->WB_stage;')
        lines.append(f'{instance}->frontendModel.de_stage_ptr=&{instance}->DE_stage;')
        lines.append(f'{instance}->frontendModel.if_stage_ptr=&{instance}->IF_stage;')
        lines.append(f'{instance}->frontendModel.wb_stage_ptr=&{instance}->WB_stage;')
        lines.append(f'{instance}->frontendModel.fetch_ptr=&{instance}->fetchModel;')
    return '\n'.join(lines)+'\n'

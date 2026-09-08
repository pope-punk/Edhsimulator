"""Payment feasibility for fixed-output mana filters, without mutating state."""
SIGNET_OUTPUTS = {'Orzhov Signet': 'WB', 'Gruul Signet': 'RG'}
PAIRED_LANDS = {'Simic Growth Chamber': 'GU'}


def payment(sources, filters, generic, need, avoid_source=None, protected=(), fixed_sources=()):
    """Try ordinary payment, then legal filter activations paid from existing units.

    Each filter is (permanent, fixed output colors). Units retain their source
    and activation-color identity, including mana spent to activate another
    filter. This prevents self-funding and circular activation dependencies.
    """
    units=[]
    free_sources={id(source) for source,_ in fixed_sources}
    for source, colors, amount in sources:
        for _ in range(amount):
            key=('treasure',len(units)) if source is None else (
                source if isinstance(source,str) else id(source))
            units.append((source,frozenset(colors),key))
    symbols=[symbol for symbol,count in need.items() for _ in range(count)]

    def priority(unit):
        source,colors,_=unit
        return (source is avoid_source, id(source) in protected, colors!={'C'})

    def match(available, fixed):
        if len(available)<generic+len(symbols):return None
        used=set();colors=dict(fixed)
        def assign(position):
            if position==len(symbols):return True
            required=set(symbols[position].split('/'))
            for index in sorted(range(len(available)),key=lambda i:available[i][0] is avoid_source):
                source,options,key=available[index]
                if index in used:continue
                candidates=options & required
                previous=colors.get(key)
                if previous is not None:candidates &= {previous}
                for color in 'WUBRGC':
                    if color not in candidates:continue
                    colors[key]=color;used.add(index)
                    if assign(position+1):return True
                    used.remove(index)
                    if previous is None:colors.pop(key,None)
                    else:colors[key]=previous
            return False
        if not assign(0):return None
        for index in sorted(range(len(available)),key=lambda i:priority(available[i])):
            if len(used)==len(symbols)+generic:break
            if index in used:continue
            _,options,key=available[index]
            colors.setdefault(key,next(c for c in 'CWUBRG' if c in options))
            used.add(index)
        return used,colors

    def variants(output):
        return (output,) if isinstance(output,str) else tuple(output)

    def search(available, remaining, fixed, feeds, activated):
        if len(available)+sum(max(len(value) for value in variants(output))-1 for _,output in remaining)<generic+len(symbols):return None
        potential=set().union(*(options for _,options,_ in available),
                              *(set().union(*(set(value) for value in variants(output))) for _,output in remaining))
        if any(not (set(symbol.split('/')) & potential) for symbol in symbols):return None
        result=match(available,fixed)
        if result is not None:
            used,colors=result
            spent=feeds+[available[i] for i in sorted(used)]
            chosen=[unit[0] for unit in spent]
            residual={}
            for source,output in activated:
                if id(source) in free_sources and not any(q is source for q in chosen):continue
                residual[id(source)]=[next(iter(options)) for i,(owner,options,_) in enumerate(available)
                                      if owner is source and i not in used]
                if not any(q is source for q in chosen):chosen.append(source)
            return chosen,colors,residual
        # No unit exists until some ordinary mana source or floating mana funds
        # the first activation. Outputs are added only AFTER its cost is paid.
        for filter_index,(source,outputs) in enumerate(remaining):
            for index in sorted(range(len(available)),key=lambda i:priority(available[i])):
                feed=available[index];_,options,key=feed
                if feed[0] is source:continue
                candidates={fixed[key]} if key in fixed else options
                for color in 'CWUBRG':
                    if color not in candidates:continue
                    for output in variants(outputs):
                        next_fixed={**fixed,key:color}
                        next_units=available[:index]+available[index+1:]
                        next_units += [(source,frozenset({c}),(id(source),c)) for c in output]
                        result=search(next_units,remaining[:filter_index]+remaining[filter_index+1:],
                                      next_fixed,feeds+[feed],activated+[(source,output)])
                        if result is not None:return result
        return None

    def choose_outputs(index, available, activated):
        if index==len(fixed_sources):
            return search(available,list(filters),{},[],activated)
        source,outputs=fixed_sources[index]
        for output in variants(outputs):
            extra=[(source,frozenset({color}),(id(source),color)) for color in output]
            result=choose_outputs(index+1,available+extra,activated+[(source,output)])
            if result is not None:return result
        return None

    return choose_outputs(0,units,[])

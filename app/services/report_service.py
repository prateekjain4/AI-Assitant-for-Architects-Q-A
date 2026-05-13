from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from io import BytesIO
import datetime

BLACK    = colors.HexColor('#000000')
SECONDARY= colors.HexColor('#f5f5f5')
DARK     = colors.HexColor('#1e293b')
GREEN_BG = colors.HexColor('#f0fdf4')
AMBER_BG = colors.HexColor('#fffbeb')
RED_BG   = colors.HexColor('#fef2f2')
BORDER   = colors.HexColor('#e2e8f0')

CITY_META = {
    'bengaluru': {
        'name':       'Bengaluru',
        'authority':  'BDA RMP 2031',
        'title':      'Bengaluru Building Regulations Report',
        'subtitle':   'BDA RMP 2031 Zoning Regulations',
        'footer_ref': 'BDA RMP 2031 Zoning Regulations, BBMP Building Bylaws, and NBC 2016 Fire Safety norms',
        'verify_with':'BBMP / BDA',
    },
    'hyderabad': {
        'name':       'Hyderabad',
        'authority':  'GHMC Rules 2012',
        'title':      'Hyderabad Building Regulations Report',
        'subtitle':   'GHMC Building Permissions Rules 2012',
        'footer_ref': 'GHMC Building Permissions Rules 2012 and NBC 2016 Fire Safety norms',
        'verify_with':'GHMC',
    },
    'ranchi': {
        'name':       'Ranchi',
        'authority':  'RMC Bye-Laws 2009',
        'title':      'Ranchi Building Regulations Report',
        'subtitle':   'RMC / RRDA Bye-Laws 2009 (JBBL)',
        'footer_ref': 'RMC Bye-Laws 2009 (JBBL) and NBC 2016 Fire Safety norms',
        'verify_with':'RMC / RRDA',
    },
}


def generate_planning_report(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm,   bottomMargin=20*mm,
    )

    SS   = getSampleStyleSheet()
    norm = SS['Normal']
    story: list = []

    # ── City metadata ─────────────────────────────────────────────
    city = (data.get('city') or 'bengaluru').lower()
    meta = CITY_META.get(city, CITY_META['bengaluru'])

    # ── Normalise field names across cities ───────────────────────
    # Plot area (sqm)
    plot_sqm  = float(data.get('plot_area_sqm') or data.get('plot_area') or 0)
    # Max built-up (sqm)
    built_sqm = float(data.get('max_built_sqm') or data.get('max_built_area') or 0)
    # If Bengaluru: plot_area is sqm, max_built_area is sqm
    # If Hyd/Ranchi: plot_area_sqm/max_built_sqm are sqm; plot_area/max_built_area are sqft
    # Hyd/Ranchi pass plot_area_sqm so the above fallback order is correct.
    # For Bengaluru the sqft equivalent is derived:
    if city == 'bengaluru':
        plot_sqft  = round(plot_sqm  * 10.764)
        built_sqft = round(built_sqm * 10.764)
    else:
        plot_sqft  = round(float(data.get('plot_area')     or plot_sqm  * 10.764))
        built_sqft = round(float(data.get('max_built_area') or built_sqm * 10.764))

    far       = data.get('far', 0) or 0
    far_base  = data.get('far_base', far)   # Bengaluru only; others default to far
    far_tdr   = data.get('far_tdr', 0) or 0
    gc_pct    = data.get('ground_coverage_pct', '-')
    staircase = data.get('staircase', {}) or {}
    num_floors= staircase.get('num_floors') or 0
    bldg_h    = data.get('building_height_m', data.get('building_height', '-'))
    h_auto    = data.get('building_height_auto', False)
    zone_label= data.get('zone_display') or data.get('zone', 'N/A')
    road_width= data.get('road_width', '-')
    locality  = data.get('locality', meta['name'])
    stair_w   = staircase.get('min_staircase_width_m') or staircase.get('stair_width_m', '-')
    setbacks  = data.get('setbacks', {}) or {}
    fire_data = data.get('fire_data', {}) or {}
    fire_rules= data.get('fire_rules') or []
    parking   = data.get('parking', {}) or {}
    p_req     = parking.get('required') or {}
    cars      = p_req.get('cars', 0) or 0
    bikes     = p_req.get('bikes') or p_req.get('two_wheelers', 0) or 0
    acc       = data.get('accessibility', {}) or {}
    basement  = data.get('basement', {}) or {}
    sections  = data.get('section_summaries', {}) or {}

    # ── Helper functions ──────────────────────────────────────────
    def section_heading(title: str):
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(
            f'<font size="10" color="#1d4ed8"><b>{title}</b></font>', norm))
        story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=3*mm))

    def metric_cell(label: str, value: str, sub: str = ''):
        body = (f'<font size="8" color="#64748b">{label}</font><br/>'
                f'<font size="12" color="#1e293b"><b>{value}</b></font>')
        if sub:
            body += f'<br/><font size="7" color="#64748b">{sub}</font>'
        return Paragraph(body, norm)

    def std_table(rows, col_widths):
        t = Table(rows, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0),  BLACK),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
            ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, SECONDARY]),
            ('BOX',           (0, 0), (-1, -1), 0.5, BORDER),
            ('INNERGRID',     (0, 0), (-1, -1), 0.3, BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        return t

    def summary_para(text: str):
        if text:
            story.append(Paragraph(
                f'<font size="8" color="#374151">{text}</font>',
                ParagraphStyle('sm', leading=12, spaceBefore=2, parent=norm)))

    def note_para(text: str, color: str = '#374151'):
        story.append(Paragraph(
            f'<font size="8" color="{color}">{text}</font>',
            ParagraphStyle('nt', spaceBefore=2, leading=12, parent=norm)))

    # ── Header ────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph(
            f'<font color="#1d4ed8" size="18"><b>PlanIQ</b></font>'
            f'<br/><font color="#64748b" size="9">{meta["title"]} — {meta["subtitle"]}</font>',
            norm),
        Paragraph(
            f'<font color="#64748b" size="8">Generated on<br/>'
            f'<b>{datetime.datetime.now().strftime("%d %B %Y, %I:%M %p")}</b></font>',
            ParagraphStyle('r', alignment=TA_RIGHT, parent=norm)),
    ]], colWidths=[120*mm, 50*mm])
    hdr.setStyle(TableStyle([
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW',    (0, 0), (-1, -1), 1, BLACK),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 8),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5*mm))

    # ── Location banner ───────────────────────────────────────────
    planning_zone = data.get('planning_zone', '')
    pz_label      = ''
    if city == 'bengaluru' and planning_zone:
        pz_label = 'Zone A (Inside ORR)' if planning_zone == 'zone_A' else 'Zone B (Outside ORR)'
    authority_label = data.get('authority', '').upper() if city == 'ranchi' else meta['authority']

    banner = Table([[
        Paragraph(
            f'<font size="11" color="white"><b>Zone: {zone_label}</b>  ·  {locality}  ·  Road {road_width} m</font>',
            norm),
        Paragraph(
            f'<font size="9" color="white">{pz_label or authority_label}</font>',
            ParagraphStyle('r', alignment=TA_RIGHT, parent=norm)),
    ]], colWidths=[110*mm, 60*mm])
    banner.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), BLACK),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (0, -1),  10),
        ('RIGHTPADDING',  (1, 0), (1, -1),  10),
    ]))
    story.append(banner)
    story.append(Spacer(1, 4*mm))

    # Warnings
    for w in (data.get('warnings') or []):
        story.append(Paragraph(
            f'<font size="8" color="#d97706">⚠ {w}</font>',
            ParagraphStyle('wn', leftIndent=6, spaceBefore=2, parent=norm)))

    # ── Key Metrics ───────────────────────────────────────────────
    section_heading('Key Metrics')

    far_util = '-'
    try:
        if plot_sqm and far:
            used_far = round(built_sqm / plot_sqm, 2)
            far_util = f"{round((used_far / far) * 100)}%"
    except Exception:
        pass

    floors_label = f'G+{num_floors - 1}' if num_floors else '-'
    floors_sub   = f'{bldg_h}m{"  (auto)" if h_auto else ""}'

    # Bengaluru shows FAR utilised; Hyd/Ranchi show FAR budget floors
    far_budget_floors = data.get('min_floors_for_max_far', '')
    last_metric = (
        metric_cell('FAR Utilised', far_util, 'of max FAR')
        if city == 'bengaluru'
        else metric_cell('FAR Budget Floors', str(far_budget_floors) if far_budget_floors else '-',
                         'to exhaust FAR · advisory')
    )
    # For Bengaluru show FAR = base+TDR; for others show zone FAR
    far_sub = f'Base {far_base} + TDR {far_tdr}' if city == 'bengaluru' else zone_label

    metrics = Table([[
        metric_cell('Plot Area',       f'{plot_sqm:,.0f} sqm',   f'({plot_sqft:,} sqft)'),
        metric_cell('Max Built-up',    f'{built_sqm:,.0f} sqm',  f'({built_sqft:,} sqft)'),
        metric_cell('FAR',             str(far),                  far_sub),
        metric_cell('Gnd Coverage',    f'{gc_pct}%',              'max allowed'),
        metric_cell('Floors Feasible', floors_label,              floors_sub),
        last_metric,
    ]], colWidths=[28*mm] * 6)
    metrics.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), SECONDARY),
        ('BOX',           (0, 0), (-1, -1), 0.5, BORDER),
        ('LINEBEFORE',    (1, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(metrics)

    # ── FAR & Built-up Area ───────────────────────────────────────
    section_heading('FAR & Built-up Area')

    if city == 'bengaluru':
        far_rows = [
            ['FAR Component', 'Value', 'Notes'],
            ['Base FAR',  str(far_base), 'BDA RMP 2031'],
            ['TDR FAR',   str(far_tdr),  'Transferable Development Rights'],
            ['Total FAR', str(far),      'Base + TDR'],
            ['Max Built-up',
             f'{built_sqm:,.0f} sqm  ({built_sqft:,} sqft)',
             f'Plot {plot_sqm:,.0f} sqm × FAR {far}'],
        ]
        excl = data.get('far_exclusions') or []
        if excl:
            far_rows.append(['FAR Exclusions', ' · '.join(excl), 'Not counted in FAR'])
        story.append(std_table(far_rows, [45*mm, 55*mm, 70*mm]))
    else:
        far_rows = [
            ['Parameter', 'Value', 'Notes'],
            ['Zone FAR',       str(far),
             f'{meta["authority"]}'],
            ['Max Built-up',
             f'{built_sqm:,.0f} sqm  ({built_sqft:,} sqft)',
             f'Plot {plot_sqm:,.0f} sqm × FAR {far}'],
            ['Ground Coverage', f'{gc_pct}%', 'Max allowed footprint'],
        ]
        story.append(std_table(far_rows, [45*mm, 55*mm, 70*mm]))

    summary_para(sections.get('far'))

    # ── Setbacks ──────────────────────────────────────────────────
    section_heading('Setback Requirements')

    sb_rows = [
        ['Direction', 'Required', 'Notes'],
        ['Front', f"{setbacks.get('front', 'N/A')} m", 'From road boundary'],
        ['Side',  f"{setbacks.get('side',  'N/A')} m", 'Each side boundary'],
        ['Rear',  f"{setbacks.get('rear',  'N/A')} m", 'From rear boundary'],
    ]
    story.append(std_table(sb_rows, [40*mm, 40*mm, 90*mm]))

    if setbacks.get('corner_relaxation'):
        note_para(f'✓ {setbacks["corner_relaxation"]}', '#16a34a')
    if setbacks.get('high_rise_rule'):
        if city == 'bengaluru':
            note_para('⚠ Progressive setbacks apply above 15 m (BDA RMP 2031 Table 2) — setbacks increase with each height tier', '#d97706')
        elif city == 'hyderabad':
            note_para('⚠ Progressive additional setbacks apply above 18 m (GHMC Rule 7 Note)', '#d97706')
        elif city == 'ranchi':
            note_para('⚠ Progressive additional setbacks apply above 22 m (RMC Table 2A-I Note)', '#d97706')
    if city in ('hyderabad', 'ranchi'):
        pl = data.get('plot_length_m', '-')
        pw = data.get('plot_width_m', '-')
        src = 'GHMC Rule 7, Table IV' if city == 'hyderabad' else 'RMC Tables 2A-I & 2A-II'
        note_para(f'Setbacks based on plot depth {pl}m × width {pw}m at {bldg_h}m height — {src}', '#64748b')
    summary_para(sections.get('setbacks'))

    # ── Compliance Summary pills ───────────────────────────────────
    section_heading('Compliance Summary')

    noc_req = fire_data.get('noc_required', False)
    comp_pills = [
        ('Setbacks', 'ok',
         f"Front {setbacks.get('front', '-')}m · Side {setbacks.get('side', '-')}m · Rear {setbacks.get('rear', '-')}m"),
        ('Fire NOC', 'warn' if noc_req else 'ok',
         'Required — contact authority' if noc_req else 'Not required at this height/area'),
        ('Lift / Elevator', 'warn' if staircase.get('lift_mandatory') else 'ok',
         f'Required above G+{num_floors - 1}' if staircase.get('lift_mandatory') else 'Not mandatory'),
        ('Accessibility', 'warn' if acc.get('required') else 'ok',
         'Ramp + accessible facilities required' if acc.get('required') else 'Not mandatory for this usage'),
        ('Parking', 'ok',
         f'{cars} car space{"s" if cars != 1 else ""} · {bikes} two-wheeler{"s" if bikes != 1 else ""} required'),
    ]
    if city == 'bengaluru':
        comp_pills.insert(4, ('Progressive Setbacks', 'warn' if num_floors > 4 else 'ok',
                              'BDA Table 2 applies — setbacks increase with height' if num_floors > 4 else 'Standard setbacks apply'))
    if city == 'hyderabad':
        comp_pills.append(('Rainwater Harvesting', 'warn', 'Mandatory for ALL buildings — GHMC Rule 15.a.vii'))

    pill_rows = []
    for i in range(0, len(comp_pills), 2):
        row = []
        for j in range(2):
            idx = i + j
            if idx < len(comp_pills):
                label, status, note_ = comp_pills[idx]
                icon  = '✓' if status == 'ok' else ('⚠' if status == 'warn' else '✗')
                ic    = '#16a34a' if status == 'ok' else ('#d97706' if status == 'warn' else '#dc2626')
                row.append(Paragraph(
                    f'<font color="{ic}" size="10"><b>{icon}</b></font> '
                    f'<font size="9" color="#1e293b"><b>{label}</b></font><br/>'
                    f'<font size="8" color="#64748b">{note_}</font>',
                    ParagraphStyle('pill', leading=13, leftIndent=2, parent=norm)))
            else:
                row.append('')
        pill_rows.append(row)

    pill_style = [
        ('BOX',          (0, 0), (-1, -1), 0.5, BORDER),
        ('INNERGRID',    (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING',   (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 8),
        ('LEFTPADDING',  (0, 0), (-1, -1), 10),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
    ]
    for i in range(0, len(comp_pills), 2):
        for j in range(2):
            idx = i + j
            if idx < len(comp_pills):
                _, status, _ = comp_pills[idx]
                bg  = GREEN_BG if status == 'ok' else (AMBER_BG if status == 'warn' else RED_BG)
                pill_style.append(('BACKGROUND', (j, i // 2), (j, i // 2), bg))
    pt = Table(pill_rows, colWidths=[85*mm, 85*mm])
    pt.setStyle(TableStyle(pill_style))
    story.append(pt)

    # ── Floors, Staircase & Lift ──────────────────────────────────
    section_heading('Floors, Staircase & Lift')

    lift_str = 'Mandatory' if staircase.get('lift_mandatory') else 'Optional'
    lift_note = staircase.get('lift_note', '')
    if not lift_note:
        if city == 'bengaluru': lift_note = 'Mandatory above G+3'
        elif city == 'hyderabad': lift_note = 'Mandatory above G+4'
        else: lift_note = 'Mandatory above G+3'

    floors_display = staircase.get('label', f'G+{num_floors - 1}' if num_floors else '-')
    st_rows = [
        ['Parameter', 'Value', 'Notes'],
        ['Floors', floors_display, f'{bldg_h} m total height'],
        ['Min Staircase Width', f'{stair_w} m', staircase.get('staircase_note', '')],
    ]
    if city == 'bengaluru':
        st_rows.append(['No. of Staircases',
                        str(staircase.get('num_staircases', '-')),
                        staircase.get('staircase_extra', '')])
    st_rows.append(['Lift', lift_str, lift_note])
    story.append(std_table(st_rows, [50*mm, 40*mm, 80*mm]))
    summary_para(sections.get('staircase'))

    # ── Fire Safety ───────────────────────────────────────────────
    section_heading('Fire Safety')

    noc_color = '#dc2626' if noc_req else '#16a34a'
    noc_text  = 'Fire NOC Required' if noc_req else '✓ Fire NOC Not Required'
    story.append(Paragraph(f'<font size="10" color="{noc_color}"><b>{noc_text}</b></font>', norm))
    if city == 'hyderabad':
        note_para('GHMC threshold: above 18 m height or BUA > 500 sqm commercial', '#64748b')
    elif city == 'ranchi':
        note_para('Special Building threshold: 16 m or ground coverage > 500 sqm', '#64748b')
    story.append(Spacer(1, 2*mm))

    tender = fire_data.get('tender_access', {}) or {}
    if tender.get('required'):
        t_rows = [
            ['Fire Tender Parameter', 'Requirement'],
            ['Min Road Width',      f"{tender.get('min_road_width_m')} m"],
            ['Height Clearance',    f"{tender.get('min_height_clearance_m')} m"],
            ['Turning Radius',      f"{tender.get('turning_radius_m')} m"],
            ['Max Dead-end Length', f"{tender.get('dead_end_max_m')} m"],
        ]
        story.append(std_table(t_rows, [80*mm, 90*mm]))
        if tender.get('note'):
            note_para(tender['note'], '#64748b')
        story.append(Spacer(1, 2*mm))

    if fire_rules:
        for rule in fire_rules:
            story.append(Paragraph(
                f'<font size="9" color="#dc2626">●</font> <font size="9">{rule}</font>',
                ParagraphStyle('bul', leftIndent=10, spaceBefore=1, parent=norm)))
    else:
        note_para('✓ No mandatory fire NOC required for this building height. Standard fire precautions apply as per NBC 2016.', '#16a34a')

    refuge = fire_data.get('refuge_area', {}) or {}
    if refuge.get('required'):
        note_para(f'⚠ Refuge area required every {refuge.get("frequency")} — min {refuge.get("min_area_sqm")} sqm.', '#d97706')
    summary_para(sections.get('fire') or fire_data.get('thresholds_note'))

    # ── Parking ───────────────────────────────────────────────────
    section_heading('Parking Requirements')

    p_area = parking.get('area') or {}
    p_loc  = parking.get('location', '-')
    p_rows = [['Parameter', 'Value'],
              ['Car Spaces Required',         str(cars)],
              ['Two-Wheeler Spaces Required', str(bikes)]]
    if p_loc and p_loc != '-':
        p_rows.append(['Parking Location', str(p_loc)])
    total_p_area = p_area.get('total_sqm', '-')
    if total_p_area != '-':
        p_rows.append(['Total Parking Area', f'{total_p_area} sqm'])

    if city == 'hyderabad':
        p_rows.append(['Regulation', 'GHMC Rule 9, Table VI'])
    elif city == 'ranchi':
        p_rows.append(['Regulation', 'NBC norms — RMC Bye-Law 21'])

    story.append(std_table(p_rows, [80*mm, 90*mm]))
    summary_para(sections.get('parking'))

    # ── Basement (if requested) ───────────────────────────────────
    if basement.get('requested'):
        section_heading('Basement')

        if city == 'bengaluru':
            b_rows = [
                ['Parameter', 'Value'],
                ['Max Basement Levels', str(basement.get('max_basements', '-'))],
                ['Max Depth', f"{basement.get('max_depth_m', '-')} m"],
            ]
            story.append(std_table(b_rows, [80*mm, 90*mm]))
            for use in (basement.get('permitted_uses') or []):
                story.append(Paragraph(f'<font size="8" color="#374151">  ✓ {use}</font>',
                                       ParagraphStyle('sm', spaceBefore=1, parent=norm)))
            if basement.get('setback_in_basement'):
                note_para(basement['setback_in_basement'], '#1d4ed8')
            if basement.get('ventilation'):
                note_para(f'⚠ {basement["ventilation"]}', '#d97706')
        else:
            # Hyd / Ranchi — simpler basement
            if basement.get('note'):
                note_para(f'⚠ {basement["note"]}', '#d97706')
            if city == 'hyderabad':
                note_para('Basement NOT counted towards FAR if used for parking only. Max 2 levels. Setback 3 m from boundary.', '#64748b')
            elif city == 'ranchi':
                note_para('Basement NOT counted towards FAR but IS counted for fee calculation purposes.', '#64748b')

    # ── Accessibility ─────────────────────────────────────────────
    if acc:
        section_heading('Accessibility')
        acc_req   = acc.get('required', False)
        acc_color = '#dc2626' if acc_req else '#16a34a'
        acc_text  = 'Accessibility Provisions Mandatory' if acc_req else 'Accessibility Recommended (not mandated)'
        story.append(Paragraph(f'<font size="9" color="{acc_color}"><b>{acc_text}</b></font>', norm))
        if acc.get('trigger'):
            note_para(acc['trigger'], '#64748b')
        story.append(Spacer(1, 2*mm))

        if city == 'bengaluru':
            ramp   = acc.get('ramp', {}) or {}
            chair  = acc.get('wheelchair', {}) or {}
            lift_  = acc.get('lift', {}) or {}
            toilet = acc.get('toilet', {}) or {}
            a_rows = [
                ['Accessibility Spec', 'Value'],
                ['Ramp Min Width',      f"{ramp.get('min_width_m', '-')} m  (slope ≤ 1:10)"],
                ['Corridor Min Width',  f"{acc.get('corridor_min_width_m', '-')} m"],
                ['Wheelchair Door',     f"{chair.get('min_door_width_mm', '-')} mm clear"],
                ['Lift Cage (D × W)',   f"{lift_.get('cage_clear_depth_mm', '-')} × {lift_.get('cage_clear_width_mm', '-')} mm"],
                ['Lift Door Width',     f"{lift_.get('entrance_door_width_mm', '-')} mm"],
                ['Accessible Toilet',   str(toilet.get('min_size_m', '-'))],
                ['Handrail Height',     f"{(acc.get('handrails') or {}).get('height_mm', '-')} mm"],
            ]
            story.append(std_table(a_rows, [80*mm, 90*mm]))
        else:
            # Hyderabad / Ranchi use richer sub-objects
            ap     = acc.get('access_path', {}) or {}
            ramp   = acc.get('ramp', {}) or {}
            hr     = acc.get('handrails', {}) or {}
            door   = acc.get('door', {}) or {}
            stair_ = acc.get('staircase', {}) or {}
            ctrl   = acc.get('controls', {}) or {}
            toilet = acc.get('toilet', {}) or {}
            pk     = acc.get('parking', {}) or {}
            a_rows = [['Accessibility Spec', 'Value']]
            if ap.get('min_width_mm'):
                a_rows.append(['Access Path Width', f"{ap.get('min_width_mm')} mm min · gradient ≤ 1:20"])
            if ramp.get('clause'):
                a_rows.append(['Ramp Max Slope', '1:12  (short runs ≤ 9000 mm)'])
            if hr.get('height_above_floor_mm'):
                a_rows.append(['Handrail Height', f"{hr.get('height_above_floor_mm')} mm · ⌀{hr.get('diameter_mm', '-')} mm"])
            if door.get('min_clear_width_mm'):
                a_rows.append(['Door Clear Width', f"{door.get('min_clear_width_mm')} mm · threshold ≤ 25 mm"])
            if stair_.get('tread_depth_mm'):
                a_rows.append(['Stair Tread / Riser', f"≥ {stair_.get('tread_depth_mm')} mm / ≤ {stair_.get('max_riser_height_mm', '-')} mm"])
            if toilet.get('ambulant_disabled_min_width_mm'):
                a_rows.append(['WC Min Size (W × D)',
                               f"{toilet.get('ambulant_disabled_min_width_mm')} × {toilet.get('ambulant_disabled_min_depth_mm', '-')} mm"])
            if len(a_rows) > 1:
                story.append(std_table(a_rows, [80*mm, 90*mm]))

    # ── Compound & Boundary Wall (Bengaluru only) ─────────────────
    bwall = data.get('boundary_wall', {}) or {}
    if bwall and city == 'bengaluru':
        section_heading('Compound & Boundary Wall')
        bw_rows = [
            ['Location', 'Max Height'],
            ['Front & Side Wall', f"{bwall.get('front_and_side_max_m', '-')} m"],
            ['Rear Wall',         f"{bwall.get('rear_max_m', '-')} m"],
        ]
        story.append(std_table(bw_rows, [80*mm, 90*mm]))
        cr = bwall.get('corner_plot_restriction')
        if cr:
            note_para(f'⚠ Corner plot: wall height restricted to {cr.get("height_m")}m for {cr.get("length_from_intersection_m")}m from intersection. {cr.get("note", "")}', '#d97706')
        note_para('✕ Barbed wire fence — Prohibited  ·  ✕ Prickly hedge — Prohibited on all boundaries', '#dc2626')

    # ── Hyderabad-specific: Solar, Water, Rainwater ───────────────
    if city == 'hyderabad':
        solar = data.get('solar', {}) or {}
        rw    = data.get('water_recycling', {}) or {}
        rwh   = data.get('rainwater_harvesting', {}) or {}

        if solar or rw or rwh:
            section_heading('Solar, Water Recycling & Rainwater')

            if solar:
                s_rows = [['Solar Parameter', 'Value']]
                s_rows.append(['Status', 'Mandatory' if solar.get('mandatory') else 'Not Required'])
                if solar.get('incentive_property_tax_rebate_pct'):
                    s_rows.append(['Property Tax Rebate', f"{solar['incentive_property_tax_rebate_pct']}%"])
                if solar.get('requirements'):
                    for req in solar['requirements']:
                        s_rows.append(['Requirement', req])
                story.append(std_table(s_rows, [80*mm, 90*mm]))
                if solar.get('bank_guarantee_required'):
                    note_para('⚠ Bank guarantee required — Rule 15.a.xi.', '#d97706')
                story.append(Spacer(1, 2*mm))

            if rw.get('requirement'):
                note_para(f'Water Recycling: {rw["requirement"]}', '#374151')
            if rw.get('incentive_clause'):
                note_para(f'✓ 10% property tax rebate when BOTH water recycling and rainwater harvesting undertaken — {rw["incentive_clause"]}', '#16a34a')

            if rwh:
                story.append(Spacer(1, 2*mm))
                pit = rwh.get('pit_dimensions', {}) or {}
                trench = rwh.get('trench_dimensions', {}) or {}
                rwh_rows = [
                    ['Rainwater Harvesting Spec', 'Value'],
                    ['Mandatory', 'YES — ALL buildings (Rule 15.a.vii)'],
                    ['Percolation Volume', f"{rwh.get('percolation_volume_per_100sqm_roof_cum', '-')} cum per 100 sqm roof"],
                ]
                if pit.get('width_m'):
                    rwh_rows.append(['Pit Dimensions (W × L × D)',
                                     f"{pit.get('width_m')} × {pit.get('length_m', '-')} × {pit.get('depth_m', '-')} m"])
                if trench.get('width_m'):
                    rwh_rows.append(['Trench Width / Depth',
                                     f"{trench.get('width_m')} m wide · {trench.get('depth_m', '-')} m deep"])
                story.append(std_table(rwh_rows, [80*mm, 90*mm]))

        # Open Space
        os_ = data.get('open_space', {}) or {}
        os_req = os_.get('requirement', {}) or {}
        if os_:
            section_heading('Organised Open Space')
            os_rows = [['Open Space Parameter', 'Value']]
            if os_req.get('min_pct_of_site'):
                os_rows.append(['Min Open Space', f"{os_req['min_pct_of_site']}% of site area"])
            chowk = os_.get('chowk', {}) or {}
            if chowk.get('min_area_sqm'):
                os_rows.append(['Chowk / Inner Courtyard', f"{chowk['min_area_sqm']} sqm min · side ≥ {chowk.get('min_side_m', '-')} m"])
            if os_req.get('green_strip_all_sides_m'):
                os_rows.append(['Green Strip (High-Rise)', f"{os_req['green_strip_all_sides_m']} m on all sides within setbacks"])
            story.append(std_table(os_rows, [80*mm, 90*mm]))
            note_para('Inter-block spacing is NOT counted as organised open space.', '#64748b')

        # Sanction & OC
        sc_  = data.get('sanction_clearance', {}) or {}
        oc_  = data.get('occupancy_certificate', {}) or {}
        pv   = sc_.get('permission_validity', {}) or {}
        if sc_ or oc_:
            section_heading('Building Sanction & Occupancy Certificate')
            sc_rows = [['Parameter', 'Value']]
            if pv.get('non_high_rise_yrs'):
                sc_rows.append(['Permission Validity (Non-High-Rise)', f"{pv['non_high_rise_yrs']} yrs from sanction"])
            if pv.get('high_rise_and_group_development_schemes_yrs'):
                sc_rows.append(['Permission Validity (High-Rise)', f"{pv['high_rise_and_group_development_schemes_yrs']} yrs from sanction"])
            if pv.get('construction_must_commence_within_months'):
                sc_rows.append(['Construction Must Start Within', f"{pv['construction_must_commence_within_months']} months"])
            if oc_.get('authority_must_respond_within_days'):
                sc_rows.append(['OC — Authority Response', f"{oc_['authority_must_respond_within_days']} days"])
            if oc_.get('mandatory') is not None:
                sc_rows.append(['Occupancy Certificate', 'Mandatory' if oc_['mandatory'] else 'Optional'])
            if sc_rows and len(sc_rows) > 1:
                story.append(std_table(sc_rows, [80*mm, 90*mm]))
            if oc_.get('penalties_without_oc'):
                note_para('Penalties without OC:', '#dc2626')
                for p in oc_['penalties_without_oc']:
                    story.append(Paragraph(f'<font size="8" color="#dc2626">⚠ {p}</font>',
                                           ParagraphStyle('bul', leftIndent=10, spaceBefore=1, parent=norm)))

    # ── Compliance & Watch Out ────────────────────────────────────
    compliance_list = data.get('compliance') or []
    watch_out       = data.get('watch_out') or []
    if compliance_list or watch_out:
        section_heading('Compliance & Watch Out')
        for item in compliance_list:
            story.append(Paragraph(
                f'<font size="9" color="#16a34a">✓</font> <font size="9">{item}</font>',
                ParagraphStyle('bul', leftIndent=10, spaceBefore=1, parent=norm)))
        if watch_out:
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph('<font size="8" color="#d97706"><b>Watch Out:</b></font>', norm))
            for w in watch_out:
                story.append(Paragraph(
                    f'<font size="9" color="#d97706">⚠</font> <font size="9">{w}</font>',
                    ParagraphStyle('bul', leftIndent=10, spaceBefore=1, parent=norm)))
        summary_para(sections.get('compliance'))

    # ── Scenario Comparison ───────────────────────────────────────
    scenarios_data = data.get('scenarios', {})
    if scenarios_data and scenarios_data.get('scenarios'):
        section_heading('Scenario Comparison')
        sc_header = ['Scenario', 'Built-up (sqft)', 'Height (m)', 'FAR Used', 'Fire NOC', 'Lift', 'Parking']
        sc_rows   = [sc_header]
        recommended = scenarios_data.get('recommended', '')
        for s in scenarios_data['scenarios']:
            label   = s.get('label', '')
            is_rec  = '★ ' + label if label == recommended else label
            exceeds = ' ⚠' if s.get('exceeds_far') else ''
            sc_rows.append([
                is_rec,
                f"{s.get('total_built_sqft', 0):,.0f}{exceeds}",
                str(s.get('building_height_m', '-')),
                f"{s.get('far_efficiency_pct', 0)}%",
                'Yes' if s.get('fire_noc_required') else 'No',
                'Yes' if s.get('lift_mandatory') else 'No',
                str(s.get('parking_car', '-')),
            ])
        sc = Table(sc_rows, colWidths=[25*mm, 30*mm, 22*mm, 20*mm, 20*mm, 16*mm, 27*mm])
        sc.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0),  BLACK),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
            ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, SECONDARY]),
            ('BOX',           (0, 0), (-1, -1), 0.5, BORDER),
            ('INNERGRID',     (0, 0), (-1, -1), 0.3, BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('ALIGN',         (1, 0), (-1, -1), 'CENTER'),
        ]))
        story.append(sc)
        story.append(Paragraph(
            f'<font size="8" color="#64748b">★ = Recommended  ·  ⚠ = Exceeds limit  ·  '
            f'FAR {scenarios_data.get("far", "")} on {scenarios_data.get("road_width", "")}m road</font>',
            ParagraphStyle('sn', spaceBefore=3, parent=norm)))

    # ── Cost Estimate (optional) ──────────────────────────────────
    cost_data = data.get('cost_estimate', {})
    if cost_data and cost_data.get('total_cost'):
        section_heading('Construction Cost Estimate')

        def fmt_cr(val):
            if not val: return '—'
            if val >= 10_000_000: return f'₹{val / 10_000_000:.2f} Cr'
            if val >= 100_000:    return f'₹{val / 100_000:.1f} L'
            return f'₹{val:,.0f}'

        tier_label = {'low': 'Basic', 'mid': 'Standard', 'high': 'Premium'}.get(
            cost_data.get('tier', 'mid'), 'Standard')
        story.append(Paragraph(
            f'<font size="8" color="#64748b">Finish tier: <b>{tier_label}</b></font>', norm))
        story.append(Spacer(1, 2*mm))

        c_rows = [['Cost Component', 'Amount', 'Source']]
        for name, key, source in [
            ('Structure',         'structure_cost',  'KPWD SR 2022'),
            ('Basement',          'basement_cost',   'KPWD SR 2022'),
            ('Finishing',         'finishing_cost',  'Market estimate'),
            ('MEP',               'mep_cost',        'Market estimate'),
            ('Site Development',  'site_dev_cost',   'KPWD SR 2022'),
            ('Parking',           'parking_cost',    'Market estimate'),
            ('Fire/Safety',       'fire_cost',       'Market estimate'),
            ('Contingency (8%)',  'contingency',     ''),
        ]:
            val = cost_data.get(key, 0)
            if val and val > 0:
                c_rows.append([name, fmt_cr(val), source])
        c_rows.append(['TOTAL ESTIMATE',
                       fmt_cr(cost_data.get('total_cost', 0)),
                       f"₹{cost_data.get('cost_per_sqm', 0):,}/sqm"])

        ct = Table(c_rows, colWidths=[70*mm, 50*mm, 50*mm])
        ct.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0),  (-1, 0),   BLACK),
            ('TEXTCOLOR',     (0, 0),  (-1, 0),   colors.white),
            ('BACKGROUND',    (0, -1), (-1, -1),  DARK),
            ('TEXTCOLOR',     (0, -1), (-1, -1),  colors.white),
            ('FONTNAME',      (0, 0),  (-1, 0),   'Helvetica-Bold'),
            ('FONTNAME',      (0, -1), (-1, -1),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0),  (-1, -1),  9),
            ('ROWBACKGROUNDS',(0, 1),  (-1, -2),  [colors.white, SECONDARY]),
            ('BOX',           (0, 0),  (-1, -1),  0.5, BORDER),
            ('INNERGRID',     (0, 0),  (-1, -1),  0.3, BORDER),
            ('TOPPADDING',    (0, 0),  (-1, -1),  6),
            ('BOTTOMPADDING', (0, 0),  (-1, -1),  6),
            ('LEFTPADDING',   (0, 0),  (-1, -1),  8),
        ]))
        story.append(ct)

    # ── Footer ────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f'<font size="7" color="#94a3b8">'
        f'This report is generated based on {meta["footer_ref"]}. It is indicative in nature and '
        f'should be verified with the relevant authority ({meta["verify_with"]}) before plan submission. '
        f'Generated by PlanIQ — planiq.in'
        f'</font>',
        ParagraphStyle('footer', alignment=TA_CENTER, parent=norm)))

    doc.build(story)
    return buffer.getvalue()
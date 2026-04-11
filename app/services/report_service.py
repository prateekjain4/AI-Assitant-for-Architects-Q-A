from reportlab.lib import styles
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from io import BytesIO
import datetime

# Brand colours
PRIMARY   = colors.HexColor('#000000')   # black
SECONDARY = colors.HexColor('#f5f5f5')   # light gray bg
DARK      = colors.HexColor('#1e293b')
MUTED     = colors.HexColor('#64748b')
GREEN     = colors.HexColor('#16a34a')
RED       = colors.HexColor('#dc2626')
AMBER     = colors.HexColor('#d97706')
BORDER    = colors.HexColor('#e2e8f0')

def generate_planning_report(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Header ────────────────────────────────────────────────────
    header_data = [[
        Paragraph(
            '<font color="#1d4ed8" size="18"><b>PlanIQ</b></font>'
            '<br/><font color="#64748b" size="9">Bangalore Building Regulations Report</font>',
            styles['Normal']
        ),
        Paragraph(
            f'<font color="#64748b" size="8">Generated on<br/>'
            f'<b>{datetime.datetime.now().strftime("%d %B %Y, %I:%M %p")}</b></font>',
            ParagraphStyle('right', alignment=TA_RIGHT, parent=styles['Normal'])
        )
    ]]
    header_table = Table(header_data, colWidths=[120*mm, 50*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('LINEBELOW',   (0,0), (-1,-1), 1, PRIMARY),
        ('BOTTOMPADDING',(0,0),(-1,-1), 8),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6*mm))

    # ── Location banner ───────────────────────────────────────────
    zone      = data.get('zone', 'N/A')
    locality  = data.get('locality', '')
    ward      = data.get('ward', '')
    confidence= data.get('confidence', '')

    location_text = f'{locality}, {ward}' if locality else 'Location not specified'
    conf_color    = '#16a34a' if confidence == 'precise' else '#d97706'
    conf_label    = '✓ Verified zone' if confidence == 'precise' else '⚠ Approximate zone'

    banner_data = [[
        Paragraph(
            f'<font size="11" color="white"><b>Zone: {zone}</b>  •  {location_text}</font>',
            styles['Normal']
        ),
        Paragraph(
            f'<font size="8" color="{conf_color}"><b>{conf_label}</b></font>',
            ParagraphStyle('right', alignment=TA_RIGHT, parent=styles['Normal'])
        )
    ]]
    banner_table = Table(banner_data, colWidths=[120*mm, 50*mm])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), PRIMARY),
        ('TEXTCOLOR',     (0,0), (-1,-1), colors.white),
        ('ROUNDEDCORNERS',(0,0), (-1,-1), [4,4,4,4]),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (0,-1), 10),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 6*mm))

    # ── Key metrics row ───────────────────────────────────────────
    def metric_cell(label, value, unit=''):
        return Paragraph(
            f'<font size="8" color="#64748b">{label}</font><br/>'
            f'<font size="14" color="#1e293b"><b>{value}</b></font>'
            f'<font size="9" color="#64748b"> {unit}</font>',
            styles['Normal']
        )

    plot_area    = data.get('plot_area', 0)
    far          = data.get('far', 0)
    max_built    = data.get('max_built_area', 0)
    road_width   = data.get('road_width', 0)
    floors = data.get("staircase", {}).get("num_floors", "-")
    metrics_data = [[
        metric_cell('Plot Area',         f'{plot_area:,.0f}', 'sq ft'),
        metric_cell('FAR',               f'{far}',            ''),
        metric_cell('Max Built-up Area', f'{max_built:,.0f}', 'sq ft'),
        metric_cell('Road Width',        f'{road_width}',     'm'),
        metric_cell('Floors',            f'{floors}',        ''),
    ]]
    metrics_table = Table(metrics_data, colWidths=[42*mm]*4)
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), SECONDARY),
        ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
        ('LINEBEFORE',    (1,0), (-1,-1), 0.5, BORDER),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('ROUNDEDCORNERS',(0,0), (-1,-1), [4,4,4,4]),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 6*mm))

    # ── Section heading helper ────────────────────────────────────
    def section_heading(title):
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(
            f'<font size="10" color="#1d4ed8"><b>{title}</b></font>',
            styles['Normal']
        ))
        story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=3*mm))

    section_heading('Feasibility Summary')

    summary = data.get("feasibility", {})

    story.append(Paragraph(
        f"""
        <b>Recommended Typology:</b> {summary.get('typology', '-')}<br/>
        <b>Floors:</b> {summary.get('floors', '-')}<br/>
        <b>Estimated Units:</b> {summary.get('units', '-')}<br/>
        <b>Risk Level:</b> {summary.get('risk', '-')}<br/>
        <b>Approval Probability:</b> {summary.get('approval', '-')}
        """,
        styles['Normal']
    ))
    section_heading('Design Options')

    options = data.get("design_options", [])
    for opt in options:
        story.append(Paragraph(
            f"""
            <b>{opt['title']}</b><br/>
            Floors: {opt['floors']}<br/>
            Units: {opt['units']}<br/>
            Parking: {opt['parking']}<br/>
            Risk: {opt['risk']}<br/><br/>
            """,
            styles['Normal']
        ))

    # ── Setbacks table ────────────────────────────────────────────
    section_heading('Setback Requirements')
    setbacks = data.get('setbacks', {})
    setback_data = [
        ['Direction', 'Required Setback', 'Notes'],
        ['Front',     f"{setbacks.get('front', 'N/A')} m", 'From road boundary'],
        ['Rear',      f"{setbacks.get('rear',  'N/A')} m", 'From rear boundary'],
        ['Side',      f"{setbacks.get('side',  'N/A')} m", 'Each side boundary'],
    ]
    setback_table = Table(setback_data, colWidths=[45*mm, 45*mm, 80*mm])
    setback_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  PRIMARY),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, SECONDARY]),
        ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID',     (0,0), (-1,-1), 0.3, BORDER),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
    ]))
    story.append(setback_table)
    # ── Staircase & Lift ──────────────────────────────────────────────
    section_heading('Staircase & Lift Requirements')
    staircase = data.get('staircase', {})
    if staircase:
        staircase_data_table = [
            ['Requirement', 'Value', 'Notes'],
            ['Min staircase width',  f"{staircase.get('min_staircase_width_m', '-')} m",  staircase.get('staircase_note', '')],
            ['Number of staircases', str(staircase.get('num_staircases', '-')),           staircase.get('staircase_extra', '')],
            ['Lift mandatory',       'Yes' if staircase.get('lift_mandatory') else 'No',  staircase.get('lift_note', '')],
        ]
        st_table = Table(staircase_data_table, colWidths=[50*mm, 30*mm, 90*mm])
        st_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0),  PRIMARY),
            ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, SECONDARY]),
            ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))
        story.append(st_table)

    # ── Fire Tender Access ────────────────────────────────────────────
    fire_data = data.get('fire_data', {})
    tender    = fire_data.get('tender_access', {})
    if tender.get('required'):
        section_heading('Fire Tender Access Requirements')
        tender_table_data = [
            ['Parameter', 'Requirement'],
            ['Min road width',       f"{tender.get('min_road_width_m')} m"],
            ['Height clearance',     f"{tender.get('min_height_clearance_m')} m"],
            ['Turning radius',       f"{tender.get('turning_radius_m')} m"],
            ['Max dead-end length',  f"{tender.get('dead_end_max_m')} m"],
        ]
        tender_table = Table(tender_table_data, colWidths=[80*mm, 90*mm])
        tender_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0),  PRIMARY),
            ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, SECONDARY]),
            ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))
        story.append(tender_table)
        story.append(Paragraph(
            f'<font size="8" color="#64748b">{tender.get("note", "")}</font>',
            styles['Normal']
        ))

    # ── Fire rules ────────────────────────────────────────────────
    section_heading('Fire Safety Requirements')
    fire_rules = data.get('fire_rules', [])
    if fire_rules:
        for rule in fire_rules:
            story.append(Paragraph(
                f'<font size="9" color="#dc2626">●</font>'
                f'<font size="9"> {rule}</font>',
                ParagraphStyle('bullet', leftIndent=10, parent=styles['Normal'])
            ))
    else:
        story.append(Paragraph(
            '<font size="9" color="#16a34a">✓ No mandatory fire NOC required for this building height. '
            'Standard fire precautions apply as per NBC 2016.</font>',
            styles['Normal']
        ))

    story.append(Spacer(1, 3*mm))
    # ── Parking Requirements ──────────────────────────────────────
    section_heading('Parking Requirements')

    parking = data.get("parking", {})

    if isinstance(parking, dict):
        required = parking.get("required") or {}
        area = parking.get("area") or {}
        location = parking.get("location", "-")

        story.append(Paragraph(
            f"""
                <b>Cars Required:</b> {required.get('cars', '-')}<br/>
                <b>Bikes Required:</b> {required.get('bikes', '-')}<br/>
                <b>Parking Location:</b> {location}<br/>
                <b>Total Parking Area:</b> {area.get('total_sqm', '-')} sqm
            """,
            styles['Normal']
        ))
    section_heading('Compliance Score')

    comp = data.get("compliance", {})

    story.append(Paragraph(
        f"""
        <b>Score:</b> {comp.get('score', '-')}/100<br/>
        <b>Status:</b> {comp.get('status', '-')}<br/><br/>

        <b>Key Issues:</b><br/>
        {"<br/>".join(comp.get('issues', []))}
        """,
        styles['Normal']
    ))
    # ── Section AI Summaries ──────────────────────────────────────
    section_summaries = data.get('section_summaries', {})
    if section_summaries:
        section_heading('AI Regulatory Summaries')
        labels = {
            'setbacks':    'Setbacks',
            'far':         'FAR & Built-up',
            'staircase':   'Staircase & Lift',
            'projections': 'Balcony & Projections',
            'basement':    'Basement',
            'fire':        'Fire Safety',
            'compliance':  'Mandatory Compliance',
            'parking':     'Parking',
        }
        for key, label in labels.items():
            val = section_summaries.get(key)
            if val:
                story.append(Paragraph(
                    f'<font size="8" color="#1d4ed8"><b>{label}:</b></font> '
                    f'<font size="8" color="#374151">{val}</font>',
                    ParagraphStyle('airow', leading=13, spaceBefore=2, parent=styles['Normal'])
                ))

    # ── Scenario Comparison ───────────────────────────────────────
    scenarios_data = data.get('scenarios', {})
    if scenarios_data and scenarios_data.get('scenarios'):
        section_heading('Scenario Comparison')
        sc_header = ['Scenario', 'Built-up (sqft)', 'Height (m)', 'FAR Used', 'Fire NOC', 'Lift', 'Parking (cars)']
        sc_rows   = [sc_header]
        recommended = scenarios_data.get('recommended', '')
        for s in scenarios_data['scenarios']:
            label     = s.get('label', '')
            is_rec    = '★ ' + label if label == recommended else label
            noc       = 'Yes' if s.get('fire_noc_required') else 'No'
            lift      = 'Yes' if s.get('lift_mandatory') else 'No'
            exceeds   = ' ⚠' if s.get('exceeds_far') else ''
            sc_rows.append([
                is_rec,
                f"{s.get('total_built_sqft', 0):,.0f}{exceeds}",
                str(s.get('building_height_m', '-')),
                f"{s.get('far_efficiency_pct', 0)}%",
                noc,
                lift,
                str(s.get('parking_car', '-')),
            ])
        sc_table = Table(sc_rows, colWidths=[22*mm, 30*mm, 22*mm, 20*mm, 20*mm, 16*mm, 30*mm])
        sc_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0),  PRIMARY),
            ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
            ('FONTSIZE',      (0,0), (-1,-1), 8),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, SECONDARY]),
            ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
            ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
        ]))
        story.append(sc_table)
        story.append(Paragraph(
            f'<font size="8" color="#64748b">★ = Recommended scenario  ·  ⚠ = Exceeds FAR/height limit  ·  '
            f'FAR {scenarios_data.get("far", "")} on {scenarios_data.get("road_width", "")}m road</font>',
            ParagraphStyle('sc_note', spaceBefore=3, parent=styles['Normal'])
        ))

    # ── Cost Estimate ─────────────────────────────────────────────
    cost_data = data.get('cost_estimate', {})
    if cost_data and cost_data.get('total_cost'):
        section_heading('Contractor & Cost Estimate')

        def fmt_cr(val):
            if not val: return '—'
            if val >= 10_000_000: return f'₹{val/10_000_000:.2f} Cr'
            if val >= 100_000:    return f'₹{val/100_000:.1f} L'
            return f'₹{val:,.0f}'

        tier_label = {'low': 'Basic', 'mid': 'Standard', 'high': 'Premium'}.get(cost_data.get('tier','mid'), 'Standard')
        story.append(Paragraph(
            f'<font size="8" color="#64748b">Finish tier: <b>{tier_label}</b>  ·  '
            f'Structure & basement: KPWD SR 2022 + BBMP 10%  ·  Finishing & MEP: Market estimates</font>',
            styles['Normal']
        ))
        story.append(Spacer(1, 2*mm))

        cost_header = ['Cost Component', 'Amount', 'Source']
        cost_rows   = [cost_header]
        components  = [
            ('Structure',       cost_data.get('structure_cost', 0),  'KPWD SR 2022'),
            ('Basement',        cost_data.get('basement_cost', 0),   'KPWD SR 2022'),
            ('Finishing',       cost_data.get('finishing_cost', 0),  'Market estimate'),
            ('MEP',             cost_data.get('mep_cost', 0),        'Market estimate'),
            ('Site Development',cost_data.get('site_dev_cost', 0),   'KPWD SR 2022'),
            ('Parking',         cost_data.get('parking_cost', 0),    'Market estimate'),
            ('Fire/Safety',     cost_data.get('fire_cost', 0),       'Market estimate'),
            ('Contingency (8%)',cost_data.get('contingency', 0),     ''),
        ]
        for name, val, source in components:
            if val and val > 0:
                cost_rows.append([name, fmt_cr(val), source])

        # Total row
        cost_rows.append(['TOTAL ESTIMATE', fmt_cr(cost_data.get('total_cost', 0)),
                          f"₹{cost_data.get('cost_per_sqm', 0):,}/sqm"])

        ct = Table(cost_rows, colWidths=[70*mm, 50*mm, 50*mm])
        ct.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),  (-1,0),   PRIMARY),
            ('TEXTCOLOR',     (0,0),  (-1,0),   colors.white),
            ('BACKGROUND',    (0,-1), (-1,-1),  DARK),
            ('TEXTCOLOR',     (0,-1), (-1,-1),  colors.white),
            ('FONTNAME',      (0,0),  (-1,0),   'Helvetica-Bold'),
            ('FONTNAME',      (0,-1), (-1,-1),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0),  (-1,-1),  9),
            ('ROWBACKGROUNDS',(0,1),  (-1,-2),  [colors.white, SECONDARY]),
            ('BOX',           (0,0),  (-1,-1),  0.5, BORDER),
            ('INNERGRID',     (0,0),  (-1,-1),  0.3, BORDER),
            ('TOPPADDING',    (0,0),  (-1,-1),  6),
            ('BOTTOMPADDING', (0,0),  (-1,-1),  6),
            ('LEFTPADDING',   (0,0),  (-1,-1),  8),
        ]))
        story.append(ct)

        # Payment milestones
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(
            '<font size="9" color="#1e293b"><b>Payment Milestone Schedule</b></font>',
            styles['Normal']
        ))
        total_cost = cost_data.get('total_cost', 0)
        milestones = [
            ('1. Mobilisation & Foundation',  15),
            ('2. Plinth & Ground Floor Slab', 25),
            ('3. Structure & Brickwork',       20),
            ('4. Finishing & Interiors',       30),
            ('5. Handover & Completion',       10),
        ]
        ms_header = ['Stage', '%', 'Amount']
        ms_rows   = [ms_header] + [[name, f'{pct}%', fmt_cr(total_cost * pct / 100)] for name, pct in milestones]
        ms_table  = Table(ms_rows, colWidths=[95*mm, 20*mm, 55*mm])
        ms_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0),  DARK),
            ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
            ('FONTSIZE',      (0,0), (-1,-1), 8),
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, SECONDARY]),
            ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('ALIGN',         (1,0), (2,-1),  'CENTER'),
        ]))
        story.append(ms_table)

        if cost_data.get('narrative'):
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph(
                f'<font size="8" color="#7c3aed">✦ </font>'
                f'<font size="8" color="#374151">{cost_data["narrative"]}</font>',
                ParagraphStyle('narrative', leading=12, parent=styles['Normal'])
            ))

    # ── Footer ────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        '<font size="7" color="#94a3b8">'
        'This report is generated based on BDA RMP 2031 Zoning Regulations, BBMP Building Bylaws, '
        'and NBC 2016 Fire Safety norms. It is indicative in nature and should be verified with '
        'the relevant authority (BBMP / BDA) before plan submission. '
        'Generated by PlanIQ — bangalore.planIQ.in'
        '</font>',
        ParagraphStyle('footer', alignment=TA_CENTER, parent=styles['Normal'])
    ))

    doc.build(story)
    return buffer.getvalue()
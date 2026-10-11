"""Vegetation geometry, auditable QA flags and actual-effort accumulation."""
import difflib
import hashlib
import numpy as np
import pandas as pd

DEFAULT_QA = {
    "expected_quadrats": 20,
    "gps_accuracy_max_m": 5.0,          # SOP 4.2
    "duration_min_range": (20, 240),    # DECISION V1: plausible survey duration in minutes
    "expected_tz_offset": "+03:00",     # DECISION V2: Kenya (EAT)
    "transect_length_m": (45, 55),      # DECISION V3: tolerance around 50 m
    "midpoint_max_offset_m": 25,        # Plot Registration SOP step 5
    "typo_similarity_cutoff": 0.8,
    "bearing_tolerance_deg": 15.0,     # Analyst review tolerance, not a SOP exemption.
    "belt_half_width_m": 2.5,
}

def parse_point(s):
    # 'lat lon alt acc' -> (lat, lon)
    if pd.isna(s):
        return (np.nan, np.nan)
    p = str(s).split()
    return float(p[0]), float(p[1])


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    x = np.sin(dl) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(x, y)) + 360) % 360



def build_transects(reg,centroids):
    """Measure recorded geometry without changing any source coordinate."""
    pref = "plot_metadata-collect_points-"
    transects = pd.DataFrame({
        "plot_name": reg["plot_name"], "centroid_id": reg["centroid_id"], "is_viable": reg["is_viable"],
        "a_lat": reg[pref + "endpoint_a-location_endpoint_a-Latitude"], "a_lon": reg[pref + "endpoint_a-location_endpoint_a-Longitude"],
        "m_lat": reg[pref + "midpoint-location_midpoint-Latitude"], "m_lon": reg[pref + "midpoint-location_midpoint-Longitude"],
        "b_lat": reg[pref + "endpoint_b-location_endpoint_b-Latitude"], "b_lon": reg[pref + "endpoint_b-location_endpoint_b-Longitude"],
    })
    cent_xy = centroids.set_index("__id")["geometry"].apply(parse_point)
    transects["c_lat"] = transects["centroid_id"].map(cent_xy.str[0])
    transects["c_lon"] = transects["centroid_id"].map(cent_xy.str[1])
    transects["length_m"] = haversine_m(transects["a_lat"], transects["a_lon"], transects["b_lat"], transects["b_lon"])
    transects["bearing_deg"] = bearing_deg(transects["a_lat"], transects["a_lon"], transects["b_lat"], transects["b_lon"])
    transects["midpoint_offset_m"] = haversine_m(transects["m_lat"], transects["m_lon"], transects["c_lat"], transects["c_lon"])

    return transects,cent_xy

def recompute_species_quadrats(survey,quad_raw,extra_raw):
    """Reconstruct the stored ODK summary definition from supplied repeat values."""
    named=(extra_raw['validated_name'].notna() & extra_raw['validated_name'].fillna('').ne(''))
    extra_counts=extra_raw.assign(has_name=named).groupby('PARENT_KEY')['has_name'].sum()
    known=quad_raw['herb_species-selected_herb_species_uuids'].fillna('').ne('')
    has_species=known | (quad_raw['KEY'].map(extra_counts).fillna(0)>0)
    counts=quad_raw.assign(has_species=has_species).groupby('PARENT_KEY')['has_species'].sum()
    result=survey.copy()
    result['recomputed_quadrats_with_species']=result['submission_key'].map(counts).fillna(0).astype(int)
    return result

def build_flags(survey,quad,extra_raw,quad_raw,vegplots,obs,known,add,typo_check,
                listed_genera,reg,transects,recorder_in_team,q_per_sub,q_numbers_ok,qa=None):
    """Return findings plus derived audit views; raw tables remain unchanged."""
    survey=recompute_species_quadrats(survey,quad_raw,extra_raw)
    add=add.copy();transects=transects.copy()
    QA=DEFAULT_QA.copy()
    if qa is not None: QA.update(qa)
    rule_registry = []
    FLAG_COLS = ["rule_id", "severity", "level", "plot_name", "submission_key", "record_key", "field", "value", "message"]
    flag_frames = []


    def add_flags(df, rule_id, severity, level, field, message, value=None, record_key="submission_key"):
        rule_registry.append({'rule_id':rule_id, 'severity':severity, 'level':level, 'field':field, 'message':message})
        if df.empty:
            return
        f = pd.DataFrame({
            "rule_id": rule_id, "severity": severity, "level": level,
            "plot_name": df.get("plot_name"), "submission_key": df.get("submission_key"),
            "record_key": df[record_key] if record_key in df else None,
            "field": field, "value": df[value].astype("string").fillna("") if value else None, "message": message,
        })
        flag_frames.append(f[FLAG_COLS])


    # ---- Survey level
    dup = survey[survey.duplicated(["survey_id", "vegplot_id"], keep=False)]
    add_flags(dup, "S01", "warning", "survey", "plot_name", "More than one submission for this survey and plot; retain review status", value="review_state")
    add_flags(survey[survey["review_state"] == "rejected"], "S02", "warning", "survey", "review_state",
              "Submission marked rejected in ODK review", value="review_state")
    add_flags(survey[survey["n_quadrats_declared"] != QA["expected_quadrats"]], "S03", "error", "survey",
              "n_quadrats_declared", "Quadrat count differs from SOP (20)", value="n_quadrats_declared")
    lo, hi = QA["duration_min_range"]
    add_flags(survey[~survey["duration_min"].between(lo, hi)], "S04", "warning", "survey", "duration_min",
              f"Survey duration outside {lo}-{hi} min", value="duration_min")
    add_flags(survey[survey["start_offset"] != QA["expected_tz_offset"]], "S05", "info", "survey", "start_time",
              "Device time-zone offset is not EAT (+03:00); check device clock", value="start_offset")
    add_flags(survey[survey["submit_lag_min"] < 0], "S06", "error", "survey", "submitted_at",
              "Submitted before survey end time", value="submit_lag_min")
    not_viable = survey.merge(vegplots[["__id", "is_viable"]], left_on="vegplot_id", right_on="__id")
    add_flags(not_viable[not_viable["is_viable"] != "yes"], "S07", "error", "survey", "vegplot_id",
              "Survey on a plot not registered as viable", value="is_viable")
    add_flags(survey[~recorder_in_team.values], "S08", "warning", "survey", "recorder_id",
              "Recorder is not among the selected team members", value="recorder")

    # ---- Quadrat level
    add_flags(quad[quad["gps_accuracy_m"] > QA["gps_accuracy_max_m"]], "Q01", "warning", "quadrat", "gps_accuracy_m",
              "Quadrat GPS accuracy worse than 5 m", value="gps_accuracy_m", record_key="quadrat_key")
    # An actually sampled empty quadrat is valid effort, not an error flag.
    add_flags(quad[quad[["lat", "lon"]].isna().any(axis=1)], "Q03", "error", "quadrat", "location",
              "Quadrat has no GPS location", record_key="quadrat_key")

    # ---- Species level
    ws = obs[obs["species_name"].astype(str).str.contains(r"^\s|\s$|\s{2,}", regex=True)]
    add_flags(ws, "SP01", "warning", "species", "species_name", "Species name has leading/trailing/double spaces",
              value="species_name", record_key="record_key")
    typos = typo_check[typo_check["closest_in_species_list"].notna()
                       & (typo_check["entered"].str.strip() != typo_check["closest_in_species_list"])]
    sp_typo = add[add["species_name"].isin(typos["entered"])].merge(
        typos.rename(columns={"entered": "species_name"}), on="species_name")
    add_flags(sp_typo, "SP02", "info", "species", "species_name",
              "Free-text name is close to a name on the species list; review (often a different species)",
              value="species_name", record_key="entry_key")
    add["genus_entered"] = add["species_name"].astype(str).str.strip().str.split().str[0]
    blank = obs[obs["species_name"].isna() | (obs["species_name"].astype(str).str.strip().isin(["", "nan"]))]
    add_flags(blank, "SP00", "error", "species", "species_name", "Species entry has no name",
              value="entry_mode", record_key="record_key")
    genus_typo = add[(add["source"] == "missing_from_list") & add["genus_entered"].notna()
                     & ~add["genus_entered"].isin(listed_genera)].copy()
    genus_typo["closest_genus"] = genus_typo["genus_entered"].apply(
        lambda g: (difflib.get_close_matches(g, listed_genera, n=1, cutoff=QA["typo_similarity_cutoff"]) or [None])[0])
    add_flags(genus_typo[genus_typo["closest_genus"].notna()], "SP03", "warning", "species", "genus",
              "Genus not on the species list but close to a listed genus (possible misspelling)",
              value="genus_entered", record_key="entry_key")


    # Additional integrity rules, surfaced as traceable findings as well as summary checks.
    add_flags(quad_raw[~quad_raw['PARENT_KEY'].isin(survey['submission_key'])].rename(columns={'KEY':'record_key'}), 'I01','error','quadrat','PARENT_KEY','Orphan quadrat parent',value='PARENT_KEY',record_key='record_key')
    add_flags(extra_raw[~extra_raw['PARENT_KEY'].isin(quad_raw['KEY'])].rename(columns={'KEY':'record_key'}), 'I02','error','species','PARENT_KEY','Orphan additional-species parent',value='PARENT_KEY',record_key='record_key')
    add_flags(survey[~survey['vegplot_id'].isin(vegplots['__id'])], 'I03','error','survey','vegplot_id','Unknown vegetation plot UUID',value='vegplot_id')
    add_flags(known[known['species_name'].isna()].assign(record_key=lambda d:d['quadrat_key']+'/species/'+d['species_id']), 'I04','error','species','species_id','Selected species UUID not in list',value='species_id',record_key='record_key')
    survey['actual_quadrats'] = survey['submission_key'].map(q_per_sub).fillna(0).astype(int)
    survey['actual_quadrats_with_herbs'] = survey['submission_key'].map(quad.groupby('submission_key')['herbs_present'].apply(lambda s:int((s=='yes').sum()))).fillna(0).astype(int)
    add_flags(survey[survey['actual_quadrats'] != QA['expected_quadrats']], 'S09','error','survey','actual_quadrats','Actual repeat rows differ from required quadrat count',value='actual_quadrats')
    numbers_bad = ~survey['submission_key'].map(q_numbers_ok).fillna(False).astype(bool)
    add_flags(survey[numbers_bad], 'S10','error','survey','quadrat_number','Quadrat numbers must be exactly 1 to 20')
    add_flags(survey[survey['quadrats_with_species_declared'] != survey['recomputed_quadrats_with_species']], 'SP05','warning','survey','quadrats_with_species_declared','Stored form calculation differs from recomputation from repeat records',value='quadrats_with_species_declared')
    bad_xy = ~(quad['lat'].between(-90,90) & quad['lon'].between(-180,180))
    add_flags(quad[bad_xy & quad[['lat','lon']].notna().all(axis=1)], 'Q07','error','quadrat','location','Coordinates outside global valid range',record_key='quadrat_key')
    contradiction = ((quad['herbs_present']=='no') & (quad['n_species_listed']>0)) | ((quad['herbs_present']=='yes') & (quad['n_species_listed']==0))
    add_flags(quad[contradiction], 'Q08','error','quadrat','herbs_present','Herb presence contradicts species list',value='herbs_present',record_key='quadrat_key')

    transects['record_key'] = reg['KEY']
    transects['submission_key'] = None
    viable = transects['is_viable'].eq('yes')
    add_flags(transects[viable & ~transects['length_m'].between(*QA['transect_length_m']) & transects['length_m'].notna()], 'P01','warning','plot','length_m','Measured endpoint length outside analyst tolerance 45-55 m; review GPS',value='length_m',record_key='record_key')
    transects['ns_deviation_deg'] = np.minimum(transects['bearing_deg'] % 180, 180-transects['bearing_deg'] % 180)
    add_flags(transects[viable & (transects['ns_deviation_deg'] > QA['bearing_tolerance_deg'])], 'P02','warning','plot','bearing_deg','Transect departs from north-south; confirm obstacle or hazard justification',value='bearing_deg',record_key='record_key')
    add_flags(transects[viable & (transects['midpoint_offset_m'] > QA['midpoint_max_offset_m'])], 'P03','warning','plot','midpoint_offset_m','Measured midpoint >25 m from planned centroid; review GPS uncertainty',value='midpoint_offset_m',record_key='record_key')
    add_flags(transects[viable & transects[['a_lat','a_lon','m_lat','m_lon','b_lat','b_lon']].isna().any(axis=1)], 'P04','error','plot','location','Viable transect missing endpoint or midpoint',record_key='record_key')

    # Small-area planar approximation at local latitude; distances are in metres.
    qgeom = quad.merge(transects[['plot_name','a_lat','a_lon','b_lat','b_lon']],on='plot_name',how='left',validate='many_to_one')
    scale = 6371000*np.pi/180
    sx = scale*np.cos(np.radians(qgeom['a_lat']))
    vx = (qgeom['b_lon']-qgeom['a_lon'])*sx; vy = (qgeom['b_lat']-qgeom['a_lat'])*scale
    px = (qgeom['lon']-qgeom['a_lon'])*sx; py = (qgeom['lat']-qgeom['a_lat'])*scale
    qgeom['projection_fraction'] = (px*vx+py*vy)/(vx*vx+vy*vy)
    qgeom['beyond_endpoint'] = (qgeom['projection_fraction']<0)|(qgeom['projection_fraction']>1)
    t = qgeom['projection_fraction'].clip(0,1)
    qgeom['distance_to_transect_m'] = np.sqrt((px-t*vx)**2+(py-t*vy)**2)
    outside = qgeom['distance_to_transect_m'] > QA['belt_half_width_m']+qgeom['gps_accuracy_m']+QA['gps_accuracy_max_m']
    add_flags(qgeom[outside], 'Q04','warning','quadrat','distance_to_transect_m','Quadrat outside transect belt plus quadrat accuracy and 5m endpoint allowance; review',value='distance_to_transect_m',record_key='quadrat_key')
    # Required photo check applies to newly encountered unknown taxa, not every reuse entry.
    new_unknown = add['entry_mode'].eq('new_unknown')
    add_flags(add[new_unknown & add['macro_images-macro_1'].isna()], 'SP04','warning','species','macro_images-macro_1','New unknown morphospecies lacks a macro photo reference',record_key='entry_key')
    # Blank quadrat comments are allowed by the SOP, so they are not flagged.
    flags = pd.concat(flag_frames, ignore_index=True)
    flags['flag_id'] = flags.apply(lambda r:hashlib.sha256('|'.join(str(r[k]) for k in ['rule_id','record_key','field']).encode()).hexdigest()[:24],axis=1)
    assert flags['flag_id'].is_unique, 'Flag identity collision: inspect issue-level record keys.'
    rule_catalogue = pd.DataFrame(rule_registry).drop_duplicates('rule_id')
    rule_catalogue['basis'] = rule_catalogue['rule_id'].map(lambda r:'analyst_review_heuristic' if r in ['S01','S04','S05','SP02','SP03','P01','P02','Q04'] else 'structural_or_SOP_check')
    rule_catalogue['rule_version'] = 'vegetation-qa-v2'

    return flags,rule_catalogue,QA,survey,transects,qgeom

def accumulation(groups,n_perm=200,seed=42):
    """Mean random-order richness using only the supplied actual sampling units."""
    if not groups:return np.array([])
    rng=np.random.default_rng(seed);curves=np.zeros((n_perm,len(groups)))
    for i in range(n_perm):
        seen=set()
        for k,j in enumerate(rng.permutation(len(groups))):
            seen |= groups[j];curves[i,k]=len(seen)
    return curves.mean(axis=0)

def spatial_rollup(qgeom,survey,qa=None):
    """Summarise geometry flags per submission, keeping record-level drill-down."""
    q=qgeom.copy()
    parameters=DEFAULT_QA.copy()
    if qa is not None:parameters.update(qa)
    q['off_line']=q['distance_to_transect_m']>(parameters.get('belt_half_width_m',2.5)+q['gps_accuracy_m']+parameters['gps_accuracy_max_m'])
    q['flagged_beyond_endpoint']=q['off_line'] & q['beyond_endpoint']
    result=q.groupby(['submission_key','plot_name']).agg(
        quadrats=('quadrat_key','size'),flagged_quadrats=('off_line','sum'),
        median_distance_m=('distance_to_transect_m','median'),
        flagged_beyond_endpoint=('flagged_beyond_endpoint','sum')).reset_index()
    result['flagged_share']=result['flagged_quadrats']/result['quadrats']
    result=result.merge(survey[['submission_key','include_in_analysis']],on='submission_key',validate='one_to_one')
    return result

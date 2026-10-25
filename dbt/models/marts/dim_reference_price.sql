-- Government consumer reference prices (HAP) and retail ceilings (HET), one row per
-- commodity x province x validity period. Source: seeds/reference_prices.csv, one row
-- per regulation x region group, each with its regulation and source_url.
-- Regulations name regions, not provinces; the region -> province map below follows
-- their wording (see dim_reference_price.yml). An unknown region gives a NULL
-- province_id, which the not_null test catches.

with regions(region, province_id) as (
    values
        -- "Jawa, Lampung dan Sumatera Selatan"
        ('jawa_lampung_sumsel', 31), ('jawa_lampung_sumsel', 32), ('jawa_lampung_sumsel', 33),
        ('jawa_lampung_sumsel', 34), ('jawa_lampung_sumsel', 35), ('jawa_lampung_sumsel', 36),
        ('jawa_lampung_sumsel', 16), ('jawa_lampung_sumsel', 18),
        -- "Aceh, Sumatera Utara, Sumatera Barat, Bengkulu, Riau, Kepulauan Riau, Jambi,
        --  dan Kepulauan Bangka Belitung" (Sumatra except Lampung and Sumatera Selatan)
        ('sumatera_lain', 11), ('sumatera_lain', 12), ('sumatera_lain', 13),
        ('sumatera_lain', 14), ('sumatera_lain', 15), ('sumatera_lain', 17),
        ('sumatera_lain', 19), ('sumatera_lain', 21),
        ('bali_ntb', 51), ('bali_ntb', 52),
        ('ntt', 53),
        ('kalimantan', 61), ('kalimantan', 62), ('kalimantan', 63),
        ('kalimantan', 64), ('kalimantan', 65),
        ('sulawesi', 71), ('sulawesi', 72), ('sulawesi', 73),
        ('sulawesi', 74), ('sulawesi', 75), ('sulawesi', 76),
        ('maluku', 81), ('maluku', 82),
        -- PIHPS still reports Papua as two provinces; the 2022 splits are inside them
        ('papua', 91), ('papua', 94)
),

seed as (
    select
        commodity_id,
        zone,
        cast(valid_from as date) as valid_from,
        cast(nullif(cast(valid_to as varchar), '') as date) as valid_to,
        price_type,
        cast(price_idr as bigint) as price_idr,
        cast(price_idr_low as bigint) as price_idr_low,
        unit,
        regulation,
        source_kind,
        source_url,
        note
    from {{ ref('reference_prices') }}
),

tokens as (
    select seed.*, unnest(string_split(zone, '|')) as region
    from seed
),

expanded as (
    select
        t.commodity_id,
        case when t.region = 'national' then p.province_id else r.province_id end
            as province_id,
        t.zone,
        t.valid_from,
        t.valid_to,
        t.price_type,
        t.price_idr,
        t.price_idr_low,
        t.unit,
        t.regulation,
        t.source_kind,
        t.source_url,
        t.note
    from tokens as t
    left join regions as r on r.region = t.region
    left join {{ ref('dim_province') }} as p on t.region = 'national'
)

select
    e.*,
    -- true when another period for the same commodity x province overlaps this one;
    -- the is_false test keeps the seed's periods clean
    exists (
        select 1
        from expanded as o
        where o.commodity_id = e.commodity_id
          and o.province_id = e.province_id
          and o.valid_from <> e.valid_from
          and o.valid_from <= coalesce(e.valid_to, date '9999-12-31')
          and e.valid_from <= coalesce(o.valid_to, date '9999-12-31')
    ) as overlaps_other_period
from expanded as e

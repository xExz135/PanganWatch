-- One row per calendar day 2018-01-01 .. 2027-12-31, with the holiday features
-- the analyses and models need. Lebaran moves ~11 days earlier each year, so the
-- day counters (not month) are what align years.

with days as (
    select cast(d as date) as date
    from generate_series(date '2018-01-01', date '2027-12-31', interval 1 day) as t(d)
),

events as (select * from {{ ref('calendar_events') }}),

holidays as (
    select event_date, string_agg(holiday_name, ' / ' order by holiday_name) as holiday_name
    from events
    where is_national_holiday
    group by event_date
),

lebaran as (select event_date from events where event_type = 'lebaran'),
idul_adha as (select event_date from events where event_type = 'idul_adha'),

ramadan as (
    select r.event_date as ramadan_start, min(l.event_date) as lebaran_date
    from events as r
    join lebaran as l on l.event_date > r.event_date
    where r.event_type = 'ramadan_start'
    group by r.event_date
),

school as (select * from {{ ref('school_holidays') }})

select
    d.date,
    year(d.date) as year,
    month(d.date) as month,
    weekofyear(d.date) as iso_week,
    isodow(d.date) as day_of_week,            -- 1 = Monday .. 7 = Sunday
    isodow(d.date) >= 6 as is_weekend,
    h.event_date is not null as is_holiday,
    h.holiday_name,
    (select min(l.event_date) from lebaran as l where l.event_date >= d.date) - d.date
        as days_to_lebaran,
    d.date - (select max(l.event_date) from lebaran as l where l.event_date <= d.date)
        as days_since_lebaran,
    r.ramadan_start is not null as is_ramadan,
    case when r.ramadan_start is not null then d.date - r.ramadan_start + 1 end as ramadan_day,
    (select min(a.event_date) from idul_adha as a where a.event_date >= d.date) - d.date
        as days_to_idul_adha,
    exists (
        select 1 from school as s where d.date between s.start_date and s.end_date
    ) as is_school_holiday,
    -- PIHPS publishes on working days only (docs/source_notes.md).
    isodow(d.date) < 6 and h.event_date is null as is_publishing_day
from days as d
left join holidays as h on h.event_date = d.date
left join ramadan as r on d.date >= r.ramadan_start and d.date < r.lebaran_date

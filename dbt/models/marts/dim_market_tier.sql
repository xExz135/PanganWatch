select market_tier, tier_order, description, pihps_price_type_id
from {{ ref('market_tiers') }}

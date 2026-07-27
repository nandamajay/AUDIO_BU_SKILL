/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Synthetic FOUND-tree fixture for test_generation_source_probe.
 * NOT the live checkout. Deterministic.
 *
 * This header DOES define OCTONARY_TDM_* macros, so:
 *   global_name_ceiling  = OCTONARY
 *   tdm_family_ceiling   = OCTONARY_TDM
 *   octonary_tdm_defined = FOUND
 *   missing_rungs        = ()   (family ceiling already at OCTONARY)
 */

#ifndef __DT_BINDINGS_Q6_LPASS_PORTS_H__
#define __DT_BINDINGS_Q6_LPASS_PORTS_H__

#define QUATERNARY_TDM_RX_0	72
#define QUATERNARY_TDM_TX_0	73
#define QUINARY_TDM_RX_0	74
#define QUINARY_TDM_TX_0	75
#define SENARY_TDM_RX_0		76
#define SEPTENARY_TDM_RX_0	78
#define OCTONARY_TDM_RX_0	80
#define OCTONARY_TDM_TX_0	81

#endif /* __DT_BINDINGS_Q6_LPASS_PORTS_H__ */

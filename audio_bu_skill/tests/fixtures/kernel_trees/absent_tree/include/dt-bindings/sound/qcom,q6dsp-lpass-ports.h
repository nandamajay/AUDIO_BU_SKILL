/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Synthetic ABSENT-tree fixture for test_generation_source_probe.
 * NOT the live checkout. Mirrors the real Nord observation:
 *   global_name_ceiling  = SENARY      (a SENARY_MI2S_* name appears)
 *   tdm_family_ceiling   = QUINARY_TDM (highest *_TDM_* prefix)
 *   octonary_tdm_defined = ABSENT
 *   missing_rungs        = (SENARY_TDM, SEPTENARY_TDM)  [OCTONARY separate]
 */

#ifndef __DT_BINDINGS_Q6_LPASS_PORTS_H__
#define __DT_BINDINGS_Q6_LPASS_PORTS_H__

#define QUATERNARY_TDM_RX_0	72
#define QUATERNARY_TDM_TX_0	73
#define QUINARY_TDM_RX_0	74
#define QUINARY_TDM_TX_0	75
#define SENARY_MI2S_RX		92
#define SENARY_MI2S_TX		93

#endif /* __DT_BINDINGS_Q6_LPASS_PORTS_H__ */

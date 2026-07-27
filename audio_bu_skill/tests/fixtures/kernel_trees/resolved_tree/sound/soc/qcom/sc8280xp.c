// SPDX-License-Identifier: GPL-2.0
/*
 * Synthetic RESOLVED-tree fixture for test_soc_descriptor.
 * NOT the live checkout. Deterministic.
 *
 * This driver .c has MODULE_DEVICE_TABLE(of, snd_sc8280xp_dt_match) and
 * match-table entries with .data = "sa8775p", so resolve_driver_source()
 * with soc_family_hint="sa8775p" → DISCOVERED.
 */

#include <linux/module.h>

static const struct of_device_id snd_sc8280xp_dt_match[] = {
	{.compatible = "qcom,sc8280xp-sndcard", "sc8280xp"},
	{.compatible = "qcom,qcs9100-sndcard", "sa8775p"},
	{.compatible = "qcom,qcs9075-sndcard", "sa8775p"},
	{}
};
MODULE_DEVICE_TABLE(of, snd_sc8280xp_dt_match);

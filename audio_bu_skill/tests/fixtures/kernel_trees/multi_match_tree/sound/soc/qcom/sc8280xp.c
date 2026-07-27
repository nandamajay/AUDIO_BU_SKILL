// SPDX-License-Identifier: GPL-2.0
/*
 * Synthetic MULTI-MATCH fixture: first file with "sa8775p" in data.
 */
#include <linux/module.h>

static const struct of_device_id snd_sc8280xp_dt_match[] = {
	{.compatible = "qcom,qcs9100-sndcard", "sa8775p"},
	{}
};
MODULE_DEVICE_TABLE(of, snd_sc8280xp_dt_match);

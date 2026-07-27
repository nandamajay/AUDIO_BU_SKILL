// SPDX-License-Identifier: GPL-2.0
/*
 * Synthetic FOUND-tree fixture for test_generation_source_probe.
 * NOT the live checkout. Deterministic; edit only with the probe contract.
 *
 * This driver .c DOES list the Nord sound-card compatible in its match
 * table, so SourceProbe.driver_match("qcom,nord-iq10-sndcard") → FOUND.
 */

#include <linux/module.h>

static const struct of_device_id snd_sc8280xp_dt_match[] = {
	{ .compatible = "qcom,sc8280xp-sndcard", .data = "sc8280xp" },
	{ .compatible = "qcom,nord-iq10-sndcard", .data = "nord-iq10" },
	{}
};
MODULE_DEVICE_TABLE(of, snd_sc8280xp_dt_match);

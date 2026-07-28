// SPDX-License-Identifier: GPL-2.0-only
/*
 * Minimal fixture reproduction of the upstream ADAU197x SPI codec driver
 * of_match_table. The adau1979 codec identity has NO adau1979.c file upstream;
 * its .compatible lives in the shared ADAU197x SPI driver alongside
 * adau1977/adau1978. CodecDriverProbe resolves adau1979 via the bounded family
 * candidate list (adau1979.c → adau1977-spi.c → ...) and selects the entry
 * whose vendor-stripped part equals the codec key. Mirrors
 * sound/soc/codecs/adau1977-spi.c on the real Nord kernel tree.
 */

static const struct of_device_id adau1977_spi_ids[] = {
	{ .compatible = "adi,adau1977" },
	{ .compatible = "adi,adau1978" },
	{ .compatible = "adi,adau1979" },
	{ }
};
MODULE_DEVICE_TABLE(of, adau1977_spi_ids);

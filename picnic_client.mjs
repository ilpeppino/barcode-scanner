#!/usr/bin/env node
import PicnicClient from "picnic-api";

/**
 * Utility helpers
 */
const env = (key) => {
  const value = process.env[key];
  return value && value.trim().length > 0 ? value.trim() : null;
};

const normalizeBarcode = (value) =>
  value ? String(value).replace(/\D+/g, "") : "";

const fatal = (message, extra = {}) => {
  const payload = { ok: false, message, ...extra };
  console.error(JSON.stringify(payload));
  process.exit(1);
};

/**
 * Parse CLI payload: node picnic_client.mjs '{"barcode":"...","quantity":1}'
 */
if (process.argv.length < 3) {
  fatal("Missing JSON payload argument.");
}

let payload;
try {
  payload = JSON.parse(process.argv[2]);
} catch (err) {
  fatal("Invalid JSON payload.", { error: err?.message });
}

const quantity = Number(payload.quantity) > 0 ? Number(payload.quantity) : 1;
const providedProductId = payload.productId || payload.product_id || null;
const providedBarcode = normalizeBarcode(payload.barcode);
const searchTerm =
  payload.searchTerm ||
  payload.title ||
  payload.name ||
  payload.query ||
  providedBarcode;

/**
 * Instantiate Picnic client
 */
const clientOptions = {};
const countryCode = env("PICNIC_COUNTRY_CODE");
const apiUrl = env("PICNIC_API_URL");
const authKey = env("PICNIC_AUTH_KEY");

if (countryCode) clientOptions.countryCode = countryCode;
if (apiUrl) clientOptions.url = apiUrl;
if (authKey) clientOptions.authKey = authKey;

const picnicClient = new PicnicClient(clientOptions);

/**
 * Ensure authentication
 */
const username = env("PICNIC_USER");
const password = env("PICNIC_PASSWORD");

const ensureAuthenticated = async () => {
  if (picnicClient.authKey) {
    return;
  }
  if (!username || !password) {
    fatal(
      "Picnic authentication required. Set PICNIC_USER and PICNIC_PASSWORD environment variables."
    );
  }
  try {
    await picnicClient.login(username, password);
  } catch (err) {
    fatal("Failed to login to Picnic.", { error: err?.message });
  }
};

/**
 * Resolve a product ID using barcode or search term.
 */
const resolveProductId = async () => {
  if (providedProductId) {
    return { productId: String(providedProductId), product: null };
  }

  if (!searchTerm) {
    fatal(
      "Unable to resolve Picnic product: provide productId or barcode/title in payload."
    );
  }

  await ensureAuthenticated();

  let results = [];
  try {
    results = await picnicClient.search(searchTerm);
  } catch (err) {
    fatal("Picnic search failed.", { error: err?.message, searchTerm });
  }

  if (!Array.isArray(results) || results.length === 0) {
    fatal("No Picnic products found for search term.", { searchTerm });
  }

  const normalizedBarcode = normalizeBarcode(providedBarcode);
  const pickByBarcode =
    normalizedBarcode &&
    results.find((item) => {
      const candidate =
        normalizeBarcode(item?.gtin) ||
        normalizeBarcode(item?.barcode) ||
        normalizeBarcode(item?.id);
      return candidate === normalizedBarcode;
    });

  const pickByTitle =
    !pickByBarcode &&
    payload.title &&
    results.find((item) =>
      String(item?.name || item?.title || "")
        .toLowerCase()
        .includes(String(payload.title).toLowerCase())
    );

  const selectedProduct = pickByBarcode || pickByTitle || results[0];

  const candidateIds = [
    selectedProduct?.id,
    selectedProduct?.productId,
    selectedProduct?.product_id,
    selectedProduct?.articleId,
    selectedProduct?.article_id,
  ].map((value) => (value !== undefined && value !== null ? String(value) : null));

  const productId = candidateIds.find(Boolean);

  if (!productId) {
    fatal("Unable to determine Picnic product ID from search result.", {
      searchTerm,
      result: selectedProduct,
    });
  }

  return { productId, product: selectedProduct };
};

/**
 * Main execution flow
 */
const main = async () => {
  await ensureAuthenticated();

  const { productId, product } = await resolveProductId();

  try {
    await picnicClient.addProductToShoppingCart(productId, quantity);
  } catch (err) {
    fatal("Failed to add product to Picnic cart.", {
      productId,
      error: err?.message,
    });
  }

  const response = {
    ok: true,
    productId,
    quantity,
    name: product?.name || product?.title || null,
  };

  if (!authKey && picnicClient.authKey) {
    response.authKey = picnicClient.authKey;
  }

  console.log(JSON.stringify(response));
};

main().catch((err) => {
  fatal("Unexpected error while interacting with Picnic.", {
    error: err?.message,
  });
});

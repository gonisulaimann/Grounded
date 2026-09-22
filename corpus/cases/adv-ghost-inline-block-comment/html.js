function reg_exp_entity(entity_name, is_attribute_value) {
	return entity_name;
}

export const build = () => _inner();

function _inner() {
	return Object.keys(entities).map(
		/** @param {any} entity_name */ (entity_name) => reg_exp_entity(entity_name, is_attribute_value)
	);
}

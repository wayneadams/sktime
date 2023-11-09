# copyright: sktime developers, BSD-3-Clause License (see LICENSE file)
"""Unit tests common to all transformers."""

__author__ = ["mloning", "fkiraly"]
__all__ = []

import pandas as pd

from sktime.datatypes import check_is_scitype, convert_to
from sktime.tests.test_all_estimators import BaseFixtureGenerator, QuickTester
from sktime.utils._testing.estimator_checks import _assert_array_almost_equal


class TransformerFixtureGenerator(BaseFixtureGenerator):
    """Fixture generator for transformer tests.

    Fixtures parameterized
    ----------------------
    estimator_class: estimator inheriting from BaseObject
        ranges over all estimator classes not excluded by EXCLUDED_TESTS
    estimator_instance: instance of estimator inheriting from BaseObject
        ranges over all estimator classes not excluded by EXCLUDED_TESTS
        instances are generated by create_test_instance class method
    scenario: instance of TestScenario
        ranges over all scenarios returned by retrieve_scenarios
    """

    # note: this should be separate from TestAllTransformers
    #   additional fixtures, parameters, etc should be added here
    #   TestAllTransformers should contain the tests only

    estimator_type_filter = "transformer"


class TestAllTransformers(TransformerFixtureGenerator, QuickTester):
    """Module level tests for all sktime transformers."""

    def test_capability_inverse_tag_is_correct(self, estimator_instance):
        """Test that the capability:inverse_transform tag is set correctly."""
        capability_tag = estimator_instance.get_tag("capability:inverse_transform")
        skip_tag = estimator_instance.get_tag("skip-inverse-transform")
        if capability_tag and not skip_tag:
            assert estimator_instance._has_implementation_of("_inverse_transform")

    def test_remember_data_tag_is_correct(self, estimator_instance):
        """Test that the remember_data tag is set correctly."""
        fit_empty_tag = estimator_instance.get_tag("fit_is_empty", True)
        remember_data_tag = estimator_instance.get_tag("remember_data", False)
        msg = (
            'if the "remember_data" tag is set to True, then the "fit_is_empty" tag '
            "must be set to False, even if _fit is not implemented or empty. "
            "This is due to boilerplate that write to self.X in fit. "
            f"Please check these two tags in {type(estimator_instance)}."
        )
        if fit_empty_tag and remember_data_tag:
            raise AssertionError(msg)

    def _expected_trafo_output_scitype(self, X_scitype, trafo_input, trafo_output):
        """Return expected output scitype, given X scitype and input/output.

        Parameters
        ----------
        X_scitype : str, scitype of the input to transform
        trafo_input : str, scitype of "instance"
        trafo_output : str, scitype that instance is being transformed to

        Returns
        -------
        expected scitype of the output of transform
        """
        # if series-to-series: input scitype equals output scitype
        if trafo_input == "Series" and trafo_output == "Series":
            return X_scitype
        if trafo_output == "Primitives":
            return "Table"
        if trafo_input == "Series" and trafo_output == "Panel":
            if X_scitype == "Series":
                return "Panel"
            if X_scitype in ["Panel", "Hierarchical"]:
                return "Hierarchical"
        if trafo_input == "Panel" and trafo_output == "Series":
            return "Series"

    def test_fit_transform_output(self, estimator_instance, scenario):
        """Test that transform output is of expected scitype."""
        X = scenario.args["transform"]["X"]
        Xt = scenario.run(estimator_instance, method_sequence=["fit", "transform"])

        X_scitype = scenario.get_tag("X_scitype")
        trafo_input = estimator_instance.get_tag("scitype:transform-input")
        trafo_output = estimator_instance.get_tag("scitype:transform-output")

        # get metadata for X and ensure that X_scitype tag was correct
        valid_X_scitype, _, X_metadata = check_is_scitype(
            X, scitype=X_scitype, return_metadata=True
        )
        msg = (
            f"error with scenario {type(scenario).__name__}, X_scitype tag "
            f'was "{X_scitype}", but check_is_scitype does not confirm this'
        )
        assert valid_X_scitype, msg

        Xt_expected_scitype = self._expected_trafo_output_scitype(
            X_scitype, trafo_input, trafo_output
        )

        valid_scitype, _, Xt_metadata = check_is_scitype(
            Xt, scitype=Xt_expected_scitype, return_metadata=True
        )

        msg = (
            f"{type(estimator_instance).__name__}.transform should return an object of "
            f"scitype {Xt_expected_scitype} when given an input of scitype {X_scitype},"
            f" but found the following return: {Xt}"
        )
        assert valid_scitype, msg

        # we now know that Xt has its expected scitype
        # assign this variable for better readability
        Xt_scitype = Xt_expected_scitype

        # skip the "number of instances" test below for Aggregator, Reconciler
        #   reason: this adds "pseudo-instances" for the __total and increases the count
        #   todo: we probably want to mirror this into a "hierarchical" tag later on
        if type(estimator_instance).__name__ in ["Aggregator", "Reconciler"]:
            return None

        # if DataFrame is returned, columns must be unique
        if hasattr(Xt, "columns"):
            msg = (
                f"{type(estimator_instance).__name__}.transform return should have "
                f"unique column indices, but found {Xt.columns}"
            )
            assert Xt.columns.is_unique, msg

        # if we vectorize, number of instances before/after transform should be same

        # series-to-series transformers
        if trafo_input == "Series" and trafo_output == "Series":
            if X_scitype == "Series" and Xt_scitype == "Series":
                if estimator_instance.get_tag("transform-returns-same-time-index"):
                    assert X.shape[0] == Xt.shape[0]
            if X_scitype == "Panel" and Xt_scitype == "Panel":
                assert X_metadata["n_instances"] == Xt_metadata["n_instances"]
            if X_scitype == "Hierarchical" and Xt_scitype == "Hierarchical":
                assert X_metadata["n_instances"] == Xt_metadata["n_instances"]

        # panel-to-panel transformers
        if trafo_input == "Panel" and trafo_output == "Panel":
            if X_scitype == "Hierarchical" and Xt_scitype == "Hierarchical":
                assert X_metadata["n_panels"] == Xt_metadata["n_panels"]

        # series-to-primitives transformers
        if trafo_input == "Series" and trafo_output == "Primitives":
            if X_scitype == "Series":
                assert Xt_metadata["n_instances"] == 1
            if X_scitype == "Panel":
                assert X_metadata["n_instances"] == Xt_metadata["n_instances"]

        # todo: also test the expected mtype

    def test_transform_inverse_transform_equivalent(self, estimator_instance, scenario):
        """Test that inverse_transform is indeed inverse to transform."""
        # skip this test if the estimator does not have inverse_transform
        if not estimator_instance.get_class_tag("capability:inverse_transform", False):
            return None

        # skip this test if the estimator skips inverse_transform
        if estimator_instance.get_tag("skip-inverse-transform", False):
            return None

        # skip this test if inverse_transform is not assumed an exact inverse
        if not estimator_instance.get_tag("capability:inverse_transform:exact", True):
            return None

        X = scenario.args["transform"]["X"]
        Xt = scenario.run(estimator_instance, method_sequence=["fit", "transform"])
        Xit = estimator_instance.inverse_transform(Xt)

        # if inversion produces more indices, we subset to the original X indices
        if not estimator_instance.get_tag("transform-returns-same-time-index"):
            if isinstance(X, pd.DataFrame):
                X = X.loc[Xit.index]

        # check that the inverse transform is indeed the inverse
        # we check this only on entries within range of invertibility, if specified
        inv_range = estimator_instance.get_tag("capability:inverse_transform:range")
        if inv_range is None:
            _assert_array_almost_equal(X, Xit)
        else:
            # convert to pd.DataFrame so that we can use masks
            df_types = ["pd.DataFrame", "pd-multiindex", "pd_multiindex_hier"]
            X = convert_to(X, df_types)
            Xit = convert_to(Xit, df_types)

            # mask entries of X outside range of invertibility
            # then compare for identity
            inside_mask = (X >= inv_range[0]) * (X <= inv_range[1])
            _assert_array_almost_equal(X[inside_mask], Xit[inside_mask])


# todo: add testing of inverse_transform
# todo: refactor the below, equivalent index check

# def check_transform_returns_same_time_index(Estimator):
#     estimator = Estimator.create_test_instance()
#     if estimator.get_tag("transform-returns-same-time-index"):
#         assert issubclass(Estimator, (_SeriesToSeriesTransformer, BaseTransformer))
#         estimator = Estimator.create_test_instance()
#         fit_args = _make_args(estimator, "fit")
#         estimator.fit(*fit_args)
#         for method in ["transform", "inverse_transform"]:
#             if _has_capability(estimator, method):
#                 X = _make_args(estimator, method)[0]
#                 Xt = estimator.transform(X)
#                 np.testing.assert_array_equal(X.index, Xt.index)

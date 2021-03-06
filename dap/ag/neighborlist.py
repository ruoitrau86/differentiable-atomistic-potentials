# Copyright 2018 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""A neighborlist for autograd-based potentials"""
import autograd.numpy as np


def get_distances(positions,
                  cell,
                  cutoff_distance,
                  skin=0.01,
                  strain=np.zeros((3, 3))):
  """Get distances to atoms in a periodic unitcell.

    Parameters
    ----------

    positions: atomic positions. array-like (natoms, 3)
    cell: unit cell. array-like (3, 3)
    cutoff_distance: Maximum distance to get neighbor distances for. float
    skin: A tolerance for the cutoff_distance. float
    strain: array-like (3, 3)

    Returns
    -------

    distances : an array of dimension (atom_i, atom_j, distance) The shape is
    (natoms, natoms, nunitcells) where nunitcells is the total number of unit
    cells required to tile the space to be sure all neighbors will be found. The
    atoms that are outside the cutoff distance are zeroed.

    offsets

    """
  positions = np.array(positions)
  cell = np.array(cell)
  strain_tensor = np.eye(3) + strain
  cell = np.dot(strain_tensor, cell.T).T
  positions = np.dot(strain_tensor, positions.T).T

  inverse_cell = np.linalg.inv(cell)
  num_repeats = cutoff_distance * np.linalg.norm(inverse_cell, axis=0)

  fractional_coords = np.dot(positions, inverse_cell) % 1
  mins = np.min(np.floor(fractional_coords - num_repeats), axis=0)
  maxs = np.max(np.ceil(fractional_coords + num_repeats), axis=0)

  # Now we generate a set of cell offsets
  v0_range = np.arange(mins[0], maxs[0])
  v1_range = np.arange(mins[1], maxs[1])
  v2_range = np.arange(mins[2], maxs[2])

  xhat = np.array([1, 0, 0])
  yhat = np.array([0, 1, 0])
  zhat = np.array([0, 0, 1])

  v0_range = v0_range[:, None] * xhat[None, :]
  v1_range = v1_range[:, None] * yhat[None, :]
  v2_range = v2_range[:, None] * zhat[None, :]

  offsets = (
      v0_range[:, None, None] + v1_range[None, :, None] +
      v2_range[None, None, :])

  offsets = np.int_(offsets.reshape(-1, 3))
  # Now we have a vector of unit cell offsets (offset_index, 3)
  # We convert that to cartesian coordinate offsets
  cart_offsets = np.dot(offsets, cell)

  # we need to offset each coord by each offset.
  # This array is (atom_index, offset, 3)
  shifted_cart_coords = positions[:, None] + cart_offsets[None, :]

  # Next, we subtract each position from the array of positions
  # (atom_i, atom_j, positionvector, 3)
  pv = shifted_cart_coords - positions[:, None, None]

  # This is the distance squared
  # (atom_i, atom_j, distance_ij)
  d2 = np.sum(pv**2, axis=3)

  # The gradient of sqrt is nan at r=0, so we do this round about way to
  # avoid that.
  zeros = np.equal(d2, 0.0)
  adjusted = np.where(zeros, np.ones_like(d2), d2)
  d = np.where(zeros, np.zeros_like(d2), np.sqrt(adjusted))

  distances = np.where(d < (cutoff_distance + skin), d, np.zeros_like(d))
  return distances, offsets


def get_neighbors(i, distances, offsets, oneway=False):
  """Get the indices and distances of neighbors to atom i.

  Parameters
  ----------

  i: int, index of the atom to get neighbors for.
  distances: the distances returned from `get_distances`.

  Returns
  -------
  indices: a list of indices for the neighbors corresponding to the index of the
  original atom list.
  offsets: a list of unit cell offsets to generate the position of the neighbor.
  """

  di = distances[i]

  within_cutoff = di > 0.0

  indices = np.arange(len(distances))

  inds = indices[np.where(within_cutoff)[0]]
  offs = offsets[np.where(within_cutoff)[1]]

  return inds, np.int_(offs)


def get_neighbors_oneway(positions,
                         cell,
                         cutoff_radius,
                         skin=0.01,
                         strain=np.zeros((3, 3))):
  """A one-way neighbor list.

    Parameters
    ----------

    positions: atomic positions. array-like (natoms, 3)
    cell: unit cell. array-like (3, 3)
    cutoff_radius: Maximum radius to get neighbor distances for. float
    skin: A tolerance for the cutoff_radius. float
    strain: array-like (3, 3)

    Returns
    -------
    indices, offsets

  Note: this function works with autograd, but it has been very difficult to
  translate to Tensorflow. The challenge is because TF treats iteration
  differently, and does not like when you try to modify variables outside the
  iteration scope.

  """

  strain_tensor = np.eye(3) + strain
  cell = np.dot(strain_tensor, cell.T).T
  positions = np.dot(strain_tensor, positions.T).T
  inverse_cell = np.linalg.inv(cell)
  h = 1 / np.linalg.norm(inverse_cell, axis=0)
  N = np.floor(2 * cutoff_radius / h) + 1

  scaled = np.dot(positions, inverse_cell)
  scaled0 = np.dot(positions, inverse_cell) % 1.0

  # this is autograd compatible.
  offsets = np.int_((scaled0 - scaled).round())

  positions0 = positions + np.dot(offsets, cell)
  natoms = len(positions)
  indices = np.arange(natoms)

  v0_range = np.arange(0, N[0] + 1)
  v1_range = np.arange(-N[1], N[1] + 1)
  v2_range = np.arange(-N[2], N[2] + 1)

  xhat = np.array([1, 0, 0])
  yhat = np.array([0, 1, 0])
  zhat = np.array([0, 0, 1])

  v0_range = v0_range[:, None] * xhat[None, :]
  v1_range = v1_range[:, None] * yhat[None, :]
  v2_range = v2_range[:, None] * zhat[None, :]

  N = (
      v0_range[:, None, None] + v1_range[None, :, None] +
      v2_range[None, None, :])

  N = N.reshape(-1, 3)

  neighbors = [np.empty(0, int) for a in range(natoms)]
  displacements = [np.empty((0, 3), int) for a in range(natoms)]

  def offset_mapfn(n):
    n1, n2, n3 = n
    if n1 == 0 and (n2 < 0 or (n2 == 0 and n3 < 0)):
      return
    displacement = np.dot((n1, n2, n3), cell)

    def atoms_mapfn(a):
      d = positions0 + displacement - positions0[a]
      i = indices[(d**2).sum(1) < (cutoff_radius**2 + skin)]
      if n1 == 0 and n2 == 0 and n3 == 0:
        i = i[i > a]
      neighbors[a] = np.concatenate((neighbors[a], i))
      disp = np.empty((len(i), 3), int)
      disp[:] = (n1, n2, n3)
      disp += offsets[i] - offsets[a]
      displacements[a] = np.concatenate((displacements[a], disp))

    list(map(atoms_mapfn, range(natoms)))

  list(map(offset_mapfn, N))

  return neighbors, displacements
